/**
 * DashboardV2 - Fully Responsive Dashboard with Multi-Strategy Support
 *
 * Responsive version of the main dashboard with:
 * - Mobile-first design patterns
 * - Card view for positions on mobile
 * - Responsive grids that adapt to screen size
 * - Touch-optimized controls
 * - Multi-strategy comparison for key metrics
 * - ALL permission checks preserved from v1
 *
 * @version 2.1.0
 * @part Responsive UI - Phase 3 + Multi-Strategy Comparison
 */

import { useStatus, useRegime, useIndicators, useStartEngine, useStopEngine, useSwitchMode } from '../../hooks/useStatus'
import { useState, useMemo } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ExecuteTradeModal } from '../../components/ExecuteTradeModal'
import { SchedulerControl } from '../../components/SchedulerControl'
import { SchwabTokenBanner } from '../../components/SchwabTokenBanner'
import { PositionsDisplay } from '../../components/PositionsDisplay'
import { performanceApiV2 } from '../../api/client'
import { useAuth } from '../../contexts/AuthContext'
import { useStrategy } from '../../contexts/StrategyContext'
import { StrategyMultiSelector } from '../../components/StrategyMultiSelector'
import { useMultiStrategyPerformanceDataV2, PerformanceDataV2 } from '../../hooks/useMultiStrategyData'
import {
  STRATEGY_COLORS,
  BASELINE_STYLE,
  STRATEGY_COLOR_HEX,
  getPatternIndicator,
  StrategyStyle,
} from '../../constants/strategyColors'
import { ResponsiveCard, ResponsiveGrid, ResponsiveText, MetricCard } from '../../components/ui'
import { useIsMobileOrSmaller } from '../../hooks/useMediaQuery'
import clsx from 'clsx'

// Time range types for dashboard
type DashboardTimeRange = '90d' | 'ytd' | '1y' | 'all'

interface TimeRangeParams {
  days: number
  start_date?: string
}

function getTimeRangeParams(timeRange: DashboardTimeRange): TimeRangeParams {
  const now = new Date()

  switch (timeRange) {
    case '90d':
      return { days: 90 }
    case 'ytd': {
      const jan1 = new Date(now.getFullYear(), 0, 1)
      return { days: 0, start_date: jan1.toISOString().split('T')[0] }
    }
    case '1y':
      return { days: 365 }
    case 'all':
      return { days: 0 }
    default:
      return { days: 90 }
  }
}

function getTimeRangeLabel(timeRange: DashboardTimeRange): string {
  switch (timeRange) {
    case '90d': return '90-Day'
    case 'ytd': return 'YTD'
    case '1y': return '1-Year'
    case 'all': return 'All-Time'
    default: return ''
  }
}

/**
 * Calculate period return from cumulative returns at start and end of period.
 * Formula: ((1 + endCum/100) / (1 + startCum/100) - 1) * 100
 */
function calculatePeriodReturn(endCumReturn: number, startCumReturn: number): number {
  const startGrowth = 1 + startCumReturn / 100
  const endGrowth = 1 + endCumReturn / 100
  if (startGrowth === 0) return 0
  return (endGrowth / startGrowth - 1) * 100
}

/**
 * Calculate annualized return (CAGR) from period return and calendar days.
 * Standard CAGR Formula: ((1 + periodReturn)^(365/calendarDays) - 1) * 100
 */
function calculateAnnualizedReturn(periodReturnPct: number, calendarDays: number): number {
  if (calendarDays <= 0) return 0
  const periodReturn = periodReturnPct / 100
  const base = 1 + periodReturn
  if (base <= 0) return -100
  const annualized = Math.pow(base, 365 / calendarDays) - 1
  return annualized * 100
}

/**
 * Calculate calendar days between first and last snapshot in history.
 */
function calculateCalendarDays(history: Array<{ timestamp?: string; trading_date?: string }>): number {
  if (!history || history.length < 2) return history?.length || 0
  // v2 API returns history in DESC order (newest first), so:
  // history[0] = newest date, history[length-1] = oldest date
  const newestDate = (history[0].trading_date || history[0].timestamp)?.slice(0, 10)
  const oldestDate = (history[history.length - 1].trading_date || history[history.length - 1].timestamp)?.slice(0, 10)
  if (!newestDate || !oldestDate) return 0
  const start = new Date(oldestDate)
  const end = new Date(newestDate)
  const diffMs = end.getTime() - start.getTime()
  return Math.floor(diffMs / (1000 * 60 * 60 * 24)) + 1
}

/**
 * Calculate Sharpe Ratio from daily returns.
 * Sharpe = Mean Daily Return / Std Dev of Daily Returns, annualized with sqrt(252)
 */
function calculateSharpeRatio(dailyReturns: number[]): number {
  if (!dailyReturns || dailyReturns.length < 2) return 0
  
  const n = dailyReturns.length
  const mean = dailyReturns.reduce((a, b) => a + b, 0) / n
  const variance = dailyReturns.reduce((sum, r) => sum + Math.pow(r - mean, 2), 0) / (n - 1)
  const stdDev = Math.sqrt(variance)
  
  if (stdDev === 0) return 0
  
  // Annualize: Sharpe = sqrt(252) * mean / stdDev
  return (Math.sqrt(252) * mean) / stdDev
}

/**
 * Calculate Max Drawdown from a series of portfolio values.
 * Returns the percentage as a negative number (e.g., -15.5 for -15.5% drawdown)
 */
function calculateMaxDrawdownFromValues(values: number[]): number {
  if (!values || values.length < 2) return 0
  
  let maxDrawdown = 0
  let peak = values[0]
  
  for (const value of values) {
    if (value > peak) {
      peak = value
    }
    const drawdown = (value - peak) / peak
    if (drawdown < maxDrawdown) {
      maxDrawdown = drawdown
    }
  }
  
  return maxDrawdown * 100  // Return as percentage
}

// Helper to format metric values
function formatMetricValue(value: number | null | undefined, format: 'percent' | 'currency' | 'number'): string {
  if (value === null || value === undefined) return '—'

  switch (format) {
    case 'percent':
      return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
    case 'currency':
      return `$${value.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
    case 'number':
      return value.toFixed(2)
    default:
      return String(value)
  }
}

// Find best value in comparison
function findBestValue(values: Record<string, number | null | undefined>, higherIsBetter = true): string | null {
  let bestId: string | null = null
  let bestValue: number | null = null

  Object.entries(values).forEach(([id, value]) => {
    if (value === null || value === undefined) return
    if (bestValue === null) {
      bestId = id
      bestValue = value
    } else if (higherIsBetter ? value > bestValue : value < bestValue) {
      bestId = id
      bestValue = value
    }
  })

  return bestId
}

function DashboardV2() {
  const { data: status, isLoading: statusLoading } = useStatus()
  const { data: regime } = useRegime()
  const { data: indicators } = useIndicators()
  const startEngine = useStartEngine()
  const stopEngine = useStopEngine()
  const switchMode = useSwitchMode()
  const queryClient = useQueryClient()
  const { hasPermission } = useAuth()
  const { compareStrategies, getStrategyDisplayName } = useStrategy()
  const isMobile = useIsMobileOrSmaller()

  // Use compareStrategies for multi-strategy or default to first
  const selectedStrategies = compareStrategies.length > 0 ? compareStrategies : []
  const primaryStrategy = selectedStrategies[0]
  const isComparisonMode = selectedStrategies.length > 1

  // Build strategy styles for comparison
  const strategyStyles = useMemo(() => {
    const styles: Record<string, StrategyStyle> = {}
    selectedStrategies.forEach((id, index) => {
      styles[id] = STRATEGY_COLORS[index] || STRATEGY_COLORS[0]
    })
    return styles
  }, [selectedStrategies])

  // Time range state for portfolio metrics
  const [timeRange, setTimeRange] = useState<DashboardTimeRange>('90d')

  // Calculate query params based on time range
  const queryParams = useMemo(() => getTimeRangeParams(timeRange), [timeRange])

  // Fetch single strategy performance data (v2 API)
  const { data: performanceData } = useQuery({
    queryKey: ['performance-v2', queryParams.days, primaryStrategy],
    queryFn: async () => {
      const [dailyRes, historyRes] = await Promise.all([
        performanceApiV2.getDaily(primaryStrategy, { mode: undefined }),
        performanceApiV2.getHistory(primaryStrategy, { mode: undefined, days: queryParams.days || 365 }),
      ])
      return {
        data: dailyRes.data.data,
        history: historyRes.data.history,
        baseline: dailyRes.data.baseline,
        is_finalized: dailyRes.data.is_finalized,
      } as PerformanceDataV2
    },
    refetchInterval: 30000,
    enabled: selectedStrategies.length === 1 && !!primaryStrategy,
  })

  // Multi-strategy performance data (v2 API)
  const { data: multiPerformanceData, isLoading: isMultiLoading } = useMultiStrategyPerformanceDataV2(
    selectedStrategies,
    { mode: undefined, days: queryParams.days || 365 },
    selectedStrategies.length > 1
  )

  // Get latest baseline from most recent snapshot
  // In comparison mode, get from first strategy's data
  // NOTE: v2 API returns history in DESC order (newest first at index 0)
  const latestSnapshot = isComparisonMode && primaryStrategy
    ? multiPerformanceData?.[primaryStrategy]?.history?.[0]
    : performanceData?.history?.[0]
  const baselineValue = latestSnapshot?.baseline_value

  // Calculate period-specific returns and baseline metrics
  // In comparison mode, use first strategy's data from multiPerformanceData for baseline calculations
  const periodMetrics = useMemo(() => {
    // Get history from either single strategy data or first strategy in comparison mode
    const historySource = performanceData?.history ||
      (primaryStrategy && multiPerformanceData?.[primaryStrategy]?.history) ||
      []

    if (!historySource || historySource.length === 0) {
      return {
        periodReturn: 0,
        periodBaselineReturn: 0,
        periodAlpha: 0,
        annualizedReturn: 0,
        baselineAnnualizedReturn: 0,
        calendarDays: 0,
        baselineSharpe: 0,
        baselineMaxDrawdown: 0
      }
    }

    const history = historySource
    // v2 API returns history in DESC order (newest first)
    // firstSnapshot = oldest date, lastSnapshot = newest date (chronologically)
    const firstSnapshot = history[history.length - 1]
    const lastSnapshot = history[0]
    const calendarDays = calculateCalendarDays(history)

    // Calculate daily baseline returns for Sharpe ratio
    const dailyBaselineReturns: number[] = []
    for (let i = 1; i < history.length; i++) {
      const prevReturn = history[i - 1].baseline_return ?? 0
      const currReturn = history[i].baseline_return ?? 0
      // Convert cumulative returns to daily return
      const prevGrowth = 1 + prevReturn / 100
      const currGrowth = 1 + currReturn / 100
      if (prevGrowth !== 0) {
        const dailyReturn = (currGrowth / prevGrowth - 1) * 100
        dailyBaselineReturns.push(dailyReturn)
      }
    }

    // Calculate baseline Sharpe ratio
    const baselineSharpe = calculateSharpeRatio(dailyBaselineReturns)

    // Extract baseline values for max drawdown calculation
    const baselineValues = history
      .map(s => s.baseline_value)
      .filter((v): v is number => v !== undefined && v !== null)

    // Calculate baseline max drawdown
    const baselineMaxDrawdown = calculateMaxDrawdownFromValues(baselineValues)

    if (timeRange === 'all') {
      const cumReturn = lastSnapshot.cumulative_return ?? 0
      const baseReturn = lastSnapshot.baseline_return ?? 0
      // v2 API returns decimals, calculateAnnualizedReturn expects percentages
      const annualizedReturn = calculateAnnualizedReturn(cumReturn * 100, calendarDays)
      const baselineAnnualizedReturn = calculateAnnualizedReturn(baseReturn * 100, calendarDays)
      return {
        periodReturn: cumReturn,
        periodBaselineReturn: baseReturn,
        periodAlpha: cumReturn - baseReturn,
        annualizedReturn,
        baselineAnnualizedReturn,
        calendarDays,
        baselineSharpe,
        baselineMaxDrawdown
      }
    }

    const periodReturn = calculatePeriodReturn(
      lastSnapshot.cumulative_return ?? 0,
      firstSnapshot.cumulative_return ?? 0
    )
    const periodBaselineReturn = calculatePeriodReturn(
      lastSnapshot.baseline_return ?? 0,
      firstSnapshot.baseline_return ?? 0
    )
    // v2 API returns decimals, calculateAnnualizedReturn expects percentages
    const annualizedReturn = calculateAnnualizedReturn(periodReturn * 100, calendarDays)
    const baselineAnnualizedReturn = calculateAnnualizedReturn(periodBaselineReturn * 100, calendarDays)

    return {
      periodReturn,
      periodBaselineReturn,
      periodAlpha: periodReturn - periodBaselineReturn,
      annualizedReturn,
      baselineAnnualizedReturn,
      calendarDays,
      baselineSharpe,
      baselineMaxDrawdown
    }
  }, [performanceData?.history, multiPerformanceData, primaryStrategy, timeRange])

  const [confirmLive, setConfirmLive] = useState(false)
  const [showTradeModal, setShowTradeModal] = useState(false)

  // State for selected strategy in Decision Tree and Target Allocation sections
  const [selectedDecisionTreeStrategy, setSelectedDecisionTreeStrategy] = useState<string>(primaryStrategy || '')
  const [selectedTargetAllocationStrategy, setSelectedTargetAllocationStrategy] = useState<string>(primaryStrategy || '')

  // Extract currentCell for use in Target Allocation
  const currentCell = indicators?.indicators?.find(i => i.name === 'current_cell')?.value

  const handleTradeSuccess = () => {
    queryClient.invalidateQueries({ queryKey: ['status'] })
    queryClient.invalidateQueries({ queryKey: ['trades'] })
  }

  const handleStart = (mode: string) => {
    if (mode === 'online_live' && !confirmLive) {
      setConfirmLive(true)
      return
    }
    startEngine.mutate({ mode, confirm: confirmLive })
    setConfirmLive(false)
  }

  const handleStop = () => {
    stopEngine.mutate()
  }

  const handleModeSwitch = (mode: string) => {
    if (mode === 'online_live' && !confirmLive) {
      setConfirmLive(true)
      return
    }
    switchMode.mutate({ mode, confirm: confirmLive })
    setConfirmLive(false)
  }

  if (statusLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-400"></div>
      </div>
    )
  }

  return (
    <div className="space-y-4 sm:space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-3">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <ResponsiveText variant="h1" as="h2">
            Jutsu Trader
          </ResponsiveText>
          {hasPermission('trades:execute') && (
            <button
              onClick={() => setShowTradeModal(true)}
              className="px-4 py-2.5 sm:py-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors font-medium text-sm sm:text-base touch-target"
            >
              Execute Trade
            </button>
          )}
        </div>

        {/* Strategy Multi-Selector */}
        <StrategyMultiSelector compact={isMobile} />
      </div>

      {/* Schwab Token Status Banner - Admin Only */}
      {hasPermission('config:write') && <SchwabTokenBanner hideWhenHealthy={true} />}

      {/* Execute Trade Modal */}
      <ExecuteTradeModal
        isOpen={showTradeModal}
        onClose={() => setShowTradeModal(false)}
        onSuccess={handleTradeSuccess}
      />

      {/* Multi-Strategy Comparison - Key Metrics */}
      {isComparisonMode && (
        <ResponsiveCard padding="md">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4">
            <ResponsiveText variant="h2" as="h3">
              Strategy Comparison
            </ResponsiveText>

            {/* Time Range Buttons */}
            <div className="flex bg-slate-700/50 rounded-lg p-1 overflow-x-auto">
              {(['90d', 'ytd', '1y', 'all'] as DashboardTimeRange[]).map((range) => (
                <button
                  key={range}
                  onClick={() => setTimeRange(range)}
                  className={clsx(
                    'px-2.5 sm:px-3 py-1.5 text-xs sm:text-sm font-medium rounded-md transition-all whitespace-nowrap',
                    'min-h-[36px] touch-target',
                    timeRange === range
                      ? 'bg-blue-600 text-white shadow-sm'
                      : 'text-gray-400 hover:text-white hover:bg-slate-600/50'
                  )}
                >
                  {range === '90d' ? '90D' : range === 'ytd' ? 'YTD' : range === '1y' ? '1Y' : 'All'}
                </button>
              ))}
            </div>
          </div>

          {isMultiLoading ? (
            <div className="flex items-center justify-center h-32">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-400"></div>
            </div>
          ) : isMobile ? (
            // Mobile Card View
            <div className="space-y-3">
              {selectedStrategies.map((strategyId, index) => {
                const perfData = multiPerformanceData?.[strategyId]
                const style = strategyStyles[strategyId]
                const history = perfData?.history || []
                // v2 API returns history in DESC order (newest first)
                const lastSnapshot = history[0]  // newest = chronologically last
                const firstSnapshot = history[history.length - 1]  // oldest = chronologically first
                const calendarDays = calculateCalendarDays(history)

                // Calculate period return (decimal form)
                let periodReturn = 0
                if (history.length > 0 && timeRange === 'all') {
                  periodReturn = lastSnapshot?.cumulative_return ?? 0
                } else if (history.length > 1) {
                  periodReturn = calculatePeriodReturn(
                    lastSnapshot?.cumulative_return ?? 0,
                    firstSnapshot?.cumulative_return ?? 0
                  )
                }
                // Convert to percentage for display and CAGR calculation
                const periodReturnPct = periodReturn * 100
                const annualizedReturn = calculateAnnualizedReturn(periodReturnPct, calendarDays)

                return (
                  <div
                    key={strategyId}
                    className="bg-slate-700/30 rounded-lg p-4"
                    style={{ borderLeft: `4px solid ${style?.color || STRATEGY_COLOR_HEX[0]}` }}
                  >
                    <div className="flex items-center gap-2 mb-3">
                      <div
                        className="w-3 h-3 rounded-full"
                        style={{ backgroundColor: style?.color || STRATEGY_COLOR_HEX[0] }}
                      />
                      <span className="text-xs text-gray-500 font-mono">
                        {getPatternIndicator(index)}
                      </span>
                      <span className="font-medium text-white">
                        {getStrategyDisplayName(strategyId).replace('Hierarchical Adaptive ', '')}
                      </span>
                    </div>

                    <div className="grid grid-cols-2 gap-3 text-sm">
                      <div>
                        <span className="text-gray-400 block">Total Equity</span>
                        <span className="text-white font-medium">
                          {formatMetricValue(perfData?.data?.total_equity, 'currency')}
                        </span>
                      </div>
                      <div>
                        <span className="text-gray-400 block">{getTimeRangeLabel(timeRange)} Return</span>
                        <span className={`font-medium ${periodReturnPct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                          {formatMetricValue(periodReturnPct, 'percent')}
                        </span>
                      </div>
                      <div>
                        <span className="text-gray-400 block">CAGR</span>
                        <span className={`font-medium ${annualizedReturn >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                          {formatMetricValue(annualizedReturn, 'percent')}
                        </span>
                      </div>
                      <div>
                        <span className="text-gray-400 block">Sharpe</span>
                        <span className="text-white font-medium">
                          {formatMetricValue(perfData?.data?.sharpe_ratio, 'number')}
                        </span>
                      </div>
                      <div className="col-span-2">
                        <span className="text-gray-400 block">Max Drawdown</span>
                        <span className="text-red-400 font-medium">
                          {formatMetricValue(
                            perfData?.data?.max_drawdown != null
                              ? -Math.abs(perfData.data.max_drawdown) * 100
                              : null,
                            'percent'
                          )}
                        </span>
                      </div>
                    </div>
                  </div>
                )
              })}

              {/* Baseline Card */}
              <div
                className="bg-slate-700/30 rounded-lg p-4"
                style={{ borderLeft: `4px solid ${BASELINE_STYLE.color}` }}
              >
                <div className="flex items-center gap-2 mb-3">
                  <div
                    className="w-3 h-3 rounded-full"
                    style={{ backgroundColor: BASELINE_STYLE.color }}
                  />
                  <span className="font-medium text-gray-400">QQQ Baseline</span>
                </div>

                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <span className="text-gray-400 block">{getTimeRangeLabel(timeRange)} Return</span>
                    <span className={`font-medium ${periodMetrics.periodBaselineReturn >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {formatMetricValue(periodMetrics.periodBaselineReturn * 100, 'percent')}
                    </span>
                  </div>
                  <div>
                    <span className="text-gray-400 block">CAGR</span>
                    <span className={`font-medium ${periodMetrics.baselineAnnualizedReturn >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {formatMetricValue(periodMetrics.baselineAnnualizedReturn, 'percent')}
                    </span>
                  </div>
                  <div>
                    <span className="text-gray-400 block">Sharpe</span>
                    <span className="text-white font-medium">
                      {formatMetricValue(periodMetrics.baselineSharpe, 'number')}
                    </span>
                  </div>
                  <div>
                    <span className="text-gray-400 block">Max Drawdown</span>
                    <span className="text-red-400 font-medium">
                      {formatMetricValue(periodMetrics.baselineMaxDrawdown, 'percent')}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            // Desktop Table View
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-slate-700">
                    <th className="text-left py-3 px-4 text-gray-400 font-medium">Metric</th>
                    {selectedStrategies.map((strategyId, index) => (
                      <th key={strategyId} className="text-center py-3 px-4">
                        <div className="flex items-center justify-center gap-2">
                          <div
                            className="w-3 h-3 rounded-full"
                            style={{ backgroundColor: strategyStyles[strategyId]?.color || STRATEGY_COLOR_HEX[0] }}
                          />
                          <span className="text-xs text-gray-500 font-mono">
                            {getPatternIndicator(index)}
                          </span>
                          <span className="text-gray-200 font-medium">
                            {getStrategyDisplayName(strategyId).replace('Hierarchical Adaptive ', '')}
                          </span>
                        </div>
                      </th>
                    ))}
                    <th className="text-center py-3 px-4">
                      <div className="flex items-center justify-center gap-2">
                        <div
                          className="w-3 h-3 rounded-full"
                          style={{ backgroundColor: BASELINE_STYLE.color }}
                        />
                        <span className="text-gray-400">QQQ</span>
                      </div>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {/* Total Equity Row */}
                  {(() => {
                    const values: Record<string, number | null | undefined> = {}
                    selectedStrategies.forEach((id) => {
                      values[id] = multiPerformanceData?.[id]?.data?.total_equity
                    })
                    const bestId = findBestValue(values, true)

                    return (
                      <tr className="border-b border-slate-700/50">
                        <td className="py-3 px-4 text-gray-300">Total Equity</td>
                        {selectedStrategies.map((strategyId) => {
                          const value = values[strategyId]
                          const isBest = strategyId === bestId
                          return (
                            <td key={strategyId} className={`py-3 px-4 text-center text-gray-200 ${isBest ? 'font-bold' : ''}`}>
                              {formatMetricValue(value, 'currency')}
                              {isBest && ' ★'}
                            </td>
                          )
                        })}
                        <td className="py-3 px-4 text-center text-amber-400 font-medium">
                          {formatMetricValue(baselineValue, 'currency')}
                        </td>
                      </tr>
                    )
                  })()}

                  {/* Period Return Row */}
                  {(() => {
                    const values: Record<string, number | null | undefined> = {}
                    selectedStrategies.forEach((id) => {
                      const perfData = multiPerformanceData?.[id]
                      const history = perfData?.history || []
                      if (history.length > 0) {
                        // v2 API returns history in DESC order (newest first)
                        const lastSnapshot = history[0]  // newest = chronologically last
                        const firstSnapshot = history[history.length - 1]  // oldest = chronologically first
                        if (timeRange === 'all') {
                          values[id] = (lastSnapshot?.cumulative_return ?? 0) * 100
                        } else if (history.length > 1) {
                          values[id] = calculatePeriodReturn(
                            lastSnapshot?.cumulative_return ?? 0,
                            firstSnapshot?.cumulative_return ?? 0
                          ) * 100
                        }
                      }
                    })
                    const bestId = findBestValue(values, true)

                    return (
                      <tr className="border-b border-slate-700/50">
                        <td className="py-3 px-4 text-gray-300">{getTimeRangeLabel(timeRange)} Return</td>
                        {selectedStrategies.map((strategyId) => {
                          const value = values[strategyId]
                          const isBest = strategyId === bestId
                          return (
                            <td key={strategyId} className={`py-3 px-4 text-center ${
                              isBest ? 'font-bold' : ''
                            } ${value !== null && value !== undefined && value >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                              {formatMetricValue(value, 'percent')}
                              {isBest && ' ★'}
                            </td>
                          )
                        })}
                        <td className={`py-3 px-4 text-center ${
                          periodMetrics.periodBaselineReturn >= 0 ? 'text-green-400' : 'text-red-400'
                        }`}>
                          {formatMetricValue(periodMetrics.periodBaselineReturn * 100, 'percent')}
                        </td>
                      </tr>
                    )
                  })()}

                  {/* CAGR Row */}
                  {(() => {
                    const values: Record<string, number | null | undefined> = {}
                    selectedStrategies.forEach((id) => {
                      const perfData = multiPerformanceData?.[id]
                      const history = perfData?.history || []
                      if (history.length > 0) {
                        // v2 API returns history in DESC order (newest first)
                        const lastSnapshot = history[0]  // newest
                        const firstSnapshot = history[history.length - 1]  // oldest
                        const calendarDays = calculateCalendarDays(history)
                        let periodReturn = 0
                        if (timeRange === 'all') {
                          periodReturn = lastSnapshot?.cumulative_return ?? 0
                        } else if (history.length > 1) {
                          periodReturn = calculatePeriodReturn(
                            lastSnapshot?.cumulative_return ?? 0,
                            firstSnapshot?.cumulative_return ?? 0
                          )
                        }
                        // Convert to percentage for CAGR calculation
                        values[id] = calculateAnnualizedReturn(periodReturn * 100, calendarDays)
                      }
                    })
                    const bestId = findBestValue(values, true)

                    return (
                      <tr className="border-b border-slate-700/50">
                        <td className="py-3 px-4 text-gray-300">CAGR</td>
                        {selectedStrategies.map((strategyId) => {
                          const value = values[strategyId]
                          const isBest = strategyId === bestId
                          return (
                            <td key={strategyId} className={`py-3 px-4 text-center ${
                              isBest ? 'font-bold' : ''
                            } ${value !== null && value !== undefined && value >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                              {formatMetricValue(value, 'percent')}
                              {isBest && ' ★'}
                            </td>
                          )
                        })}
                        <td className={`py-3 px-4 text-center ${
                          periodMetrics.baselineAnnualizedReturn >= 0 ? 'text-green-400' : 'text-red-400'
                        }`}>
                          {formatMetricValue(periodMetrics.baselineAnnualizedReturn, 'percent')}
                        </td>
                      </tr>
                    )
                  })()}

                  {/* Sharpe Ratio Row */}
                  {(() => {
                    const values: Record<string, number | null | undefined> = {}
                    selectedStrategies.forEach((id) => {
                      values[id] = multiPerformanceData?.[id]?.data?.sharpe_ratio
                    })
                    const bestId = findBestValue(values, true)

                    return (
                      <tr className="border-b border-slate-700/50">
                        <td className="py-3 px-4 text-gray-300">Sharpe Ratio</td>
                        {selectedStrategies.map((strategyId) => {
                          const value = values[strategyId]
                          const isBest = strategyId === bestId
                          return (
                            <td key={strategyId} className={`py-3 px-4 text-center text-gray-200 ${isBest ? 'font-bold' : ''}`}>
                              {formatMetricValue(value, 'number')}
                              {isBest && ' ★'}
                            </td>
                          )
                        })}
                        <td className="py-3 px-4 text-center text-gray-200">
                          {formatMetricValue(periodMetrics.baselineSharpe, 'number')}
                        </td>
                      </tr>
                    )
                  })()}

                  {/* Max Drawdown Row */}
                  {(() => {
                    const values: Record<string, number | null | undefined> = {}
                    selectedStrategies.forEach((id) => {
                      const rawValue = multiPerformanceData?.[id]?.data?.max_drawdown
                      // Negate to show as negative percentage, multiply by 100 for display
                      values[id] = rawValue != null ? -Math.abs(rawValue) * 100 : null
                    })
                    const bestId = findBestValue(values, false) // Lower (closer to 0) is better

                    return (
                      <tr className="border-b border-slate-700/50">
                        <td className="py-3 px-4 text-gray-300">Max Drawdown</td>
                        {selectedStrategies.map((strategyId) => {
                          const value = values[strategyId]
                          const isBest = strategyId === bestId
                          return (
                            <td key={strategyId} className={`py-3 px-4 text-center text-red-400 ${isBest ? 'font-bold' : ''}`}>
                              {formatMetricValue(value, 'percent')}
                              {isBest && ' ★'}
                            </td>
                          )
                        })}
                        <td className="py-3 px-4 text-center text-red-400">
                          {formatMetricValue(periodMetrics.baselineMaxDrawdown, 'percent')}
                        </td>
                      </tr>
                    )
                  })()}
                </tbody>
              </table>
            </div>
          )}
        </ResponsiveCard>
      )}

      {/* 1. Engine Control - Admin Only */}
      {hasPermission('engine:control') && (
        <ResponsiveCard padding="md">
          <ResponsiveText variant="h2" as="h3" className="mb-4">
            Engine Control
          </ResponsiveText>

          {/* Status Row - Stacks on mobile */}
          <div className="flex flex-col sm:flex-row sm:items-center gap-3 sm:gap-4 mb-4">
            <div className="flex items-center gap-2">
              <span className={`w-3 h-3 rounded-full ${
                status?.is_running ? 'bg-green-500 animate-pulse' : 'bg-gray-500'
              }`} />
              <span className="font-medium text-sm sm:text-base">
                {status?.is_running ? 'Running' : 'Stopped'}
              </span>
            </div>

            <div className="px-3 py-1.5 rounded-full text-xs sm:text-sm font-medium bg-slate-700 inline-block w-fit">
              Mode: {status?.mode === 'online_live' ? 'Live Trading' : status?.mode === 'offline_mock' ? 'Paper Trading' : status?.mode || 'N/A'}
            </div>

            {status?.uptime_seconds && (
              <div className="text-xs sm:text-sm text-gray-400">
                Uptime: {Math.floor(status.uptime_seconds / 60)}m {Math.floor(status.uptime_seconds % 60)}s
              </div>
            )}
          </div>

          {/* Control Buttons - Stack on mobile */}
          <div className="flex flex-col sm:flex-row gap-3">
            {!status?.is_running ? (
              <>
                <button
                  onClick={() => handleStart('offline_mock')}
                  className="px-4 py-2.5 bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors text-sm sm:text-base touch-target"
                >
                  Start Paper Trading
                </button>
                <button
                  onClick={() => handleStart('online_live')}
                  className="px-4 py-2.5 bg-yellow-600 hover:bg-yellow-700 rounded-lg transition-colors text-sm sm:text-base touch-target"
                >
                  Start Live Trading
                </button>
              </>
            ) : (
              <>
                <button
                  onClick={handleStop}
                  className="px-4 py-2.5 bg-red-600 hover:bg-red-700 rounded-lg transition-colors text-sm sm:text-base touch-target"
                >
                  Stop Engine
                </button>
                <select
                  value={status?.mode || ''}
                  onChange={(e) => handleModeSwitch(e.target.value)}
                  className="px-4 py-2.5 bg-slate-700 rounded-lg border border-slate-600 text-sm sm:text-base touch-target"
                >
                  <option value="offline_mock">Paper Trading</option>
                  <option value="online_live">Live Trading</option>
                </select>
              </>
            )}
          </div>

          {/* Confirm Live Trading Warning */}
          {confirmLive && (
            <div className="mt-4 p-3 sm:p-4 bg-yellow-900/30 border border-yellow-600 rounded-lg">
              <p className="text-yellow-400 font-medium mb-2 text-sm sm:text-base">
                Warning: Live trading will execute real orders with real money!
              </p>
              <div className="flex flex-col sm:flex-row gap-3">
                <button
                  onClick={() => {
                    startEngine.mutate({ mode: 'online_live', confirm: true })
                    setConfirmLive(false)
                  }}
                  className="px-4 py-2.5 bg-yellow-600 hover:bg-yellow-700 rounded-lg text-sm sm:text-base touch-target"
                >
                  Confirm Live Trading
                </button>
                <button
                  onClick={() => setConfirmLive(false)}
                  className="px-4 py-2.5 bg-slate-600 hover:bg-slate-700 rounded-lg text-sm sm:text-base touch-target"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </ResponsiveCard>
      )}

      {/* 2. Portfolio Returns - Responsive Grid (Single Strategy View Only) */}
      {status?.portfolio && !isComparisonMode && (
        <ResponsiveCard padding="md">
          {/* Header with Time Range Selector */}
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4">
            <ResponsiveText variant="h2" as="h3">
              Portfolio Returns
            </ResponsiveText>

            {/* Time Range Buttons - Scrollable on mobile */}
            <div className="flex bg-slate-700/50 rounded-lg p-1 overflow-x-auto">
              {(['90d', 'ytd', '1y', 'all'] as DashboardTimeRange[]).map((range) => (
                <button
                  key={range}
                  onClick={() => setTimeRange(range)}
                  className={clsx(
                    'px-2.5 sm:px-3 py-1.5 text-xs sm:text-sm font-medium rounded-md transition-all whitespace-nowrap',
                    'min-h-[36px] touch-target',
                    timeRange === range
                      ? 'bg-blue-600 text-white shadow-sm'
                      : 'text-gray-400 hover:text-white hover:bg-slate-600/50'
                  )}
                >
                  {range === '90d' ? '90D' : range === 'ytd' ? 'YTD' : range === '1y' ? '1Y' : 'All'}
                </button>
              ))}
            </div>
          </div>

          {/* Period Label */}
          <ResponsiveText variant="label" className="mb-2 block">
            {getTimeRangeLabel(timeRange)} Returns
          </ResponsiveText>

          {/* Metrics Grid - Responsive columns */}
          <ResponsiveGrid
            columns={{ default: 1, xs: 2, md: 3, lg: 5 }}
            gap="sm"
          >
            <MetricCard
              label="Portfolio"
              value={periodMetrics.periodReturn * 100}
              format="percent"
            />
            <MetricCard
              label="Portfolio CAGR"
              value={periodMetrics.annualizedReturn}
              format="percent"
            />
            <MetricCard
              label="QQQ Baseline"
              value={periodMetrics.periodBaselineReturn * 100}
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
              value={periodMetrics.periodAlpha * 100}
              format="percent"
              className="xs:col-span-2 md:col-span-1"
            />
          </ResponsiveGrid>
        </ResponsiveCard>
      )}

      {/* 3. Portfolio Snapshot */}
      {(isComparisonMode ? Object.keys(multiPerformanceData || {}).length > 0 : status?.portfolio) && (
        <ResponsiveCard padding="md">
          <ResponsiveText variant="h2" as="h3" className="mb-4">
            Portfolio Snapshot
          </ResponsiveText>

          {isComparisonMode ? (
            // Multi-strategy comparison view - Holdings with Cash row
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-slate-700">
                    <th className="text-left py-3 px-4 text-gray-400 font-medium">Symbol</th>
                    {selectedStrategies.map((strategyId) => (
                      <th key={strategyId} className="text-center py-3 px-4">
                        <div className="flex items-center justify-center gap-2">
                          <div
                            className="w-3 h-3 rounded-full"
                            style={{ backgroundColor: strategyStyles[strategyId]?.color || STRATEGY_COLOR_HEX[0] }}
                          />
                          <span style={{ color: strategyStyles[strategyId]?.color || STRATEGY_COLOR_HEX[0] }}>
                            {getStrategyDisplayName(strategyId).replace('Hierarchical Adaptive ', '')}
                          </span>
                        </div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {/* Cash Row */}
                  <tr className="border-b border-slate-700/50 bg-slate-700/20">
                    <td className="py-3 px-4 text-blue-400 font-medium">Cash</td>
                    {selectedStrategies.map((strategyId) => {
                      const perfData = multiPerformanceData?.[strategyId]
                      return (
                        <td key={strategyId} className="py-3 px-4 text-center">
                          <div className="text-blue-400 font-medium">
                            ${(perfData?.data?.cash ?? 0).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}
                          </div>
                        </td>
                      )
                    })}
                  </tr>
                  {/* Get all unique symbols across strategies */}
                  {(() => {
                    const allSymbols = new Set<string>()
                    selectedStrategies.forEach((strategyId) => {
                      const holdings = multiPerformanceData?.[strategyId]?.data?.holdings
                      holdings?.forEach((h: { symbol: string }) => allSymbols.add(h.symbol))
                    })
                    
                    if (allSymbols.size === 0) {
                      return (
                        <tr>
                          <td colSpan={selectedStrategies.length + 1} className="py-4 text-center text-gray-500">
                            No positions currently held
                          </td>
                        </tr>
                      )
                    }
                    
                    return Array.from(allSymbols).sort().map((symbol) => (
                      <tr key={symbol} className="border-b border-slate-700/50">
                        <td className="py-3 px-4 text-gray-200 font-medium">{symbol}</td>
                        {selectedStrategies.map((strategyId) => {
                          const holdings = multiPerformanceData?.[strategyId]?.data?.holdings as Array<{
                            symbol: string
                            quantity: number
                            value: number
                            weight_pct: number
                          }> | undefined
                          const holding = holdings?.find(h => h.symbol === symbol)
                          if (holding) {
                            return (
                              <td key={strategyId} className="py-3 px-4 text-center">
                                <div className="text-green-400 font-medium">
                                  ${holding.value.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}
                                </div>
                                <div className="text-xs text-gray-500">
                                  {holding.quantity} shares ({holding.weight_pct.toFixed(1)}%)
                                </div>
                              </td>
                            )
                          }
                          return (
                            <td key={strategyId} className="py-3 px-4 text-center text-gray-600">
                              —
                            </td>
                          )
                        })}
                      </tr>
                    ))
                  })()}
                </tbody>
              </table>
            </div>
          ) : (
            // Single strategy view (original)
            <>
              {/* Balance Grid */}
              <ResponsiveGrid
                columns={{ default: 1, xs: 2, md: 4 }}
                gap="sm"
                className="mb-6"
              >
                <MetricCard
                  label="Total Equity"
                  value={status?.portfolio?.total_equity}
                  format="currency"
                />
                <MetricCard
                  label="QQQ Baseline"
                  value={baselineValue}
                  format="currency"
                  variant="baseline"
                />
                {status?.portfolio?.cash !== undefined && (
                  <MetricCard
                    label="Cash"
                    value={status.portfolio.cash}
                    format="currency"
                    variant="neutral"
                  />
                )}
                {status?.portfolio?.positions_value !== undefined && (
                  <MetricCard
                    label="Positions Value"
                    value={status.portfolio.positions_value}
                    format="currency"
                    variant="neutral"
                  />
                )}
              </ResponsiveGrid>

              {/* Positions Display - Cards on mobile, table on tablet+ */}
              {status?.portfolio?.positions && status.portfolio.positions.length > 0 && (
                <PositionsDisplay positions={status.portfolio.positions} />
              )}
            </>
          )}
        </ResponsiveCard>
      )}

      {/* 4. Current Regime */}
      <ResponsiveCard padding="md">
        <ResponsiveText variant="h2" as="h3" className="mb-4">
          Current Regime
        </ResponsiveText>

        {isComparisonMode ? (
          // Multi-strategy table view
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-slate-700">
                  <th className="text-left py-3 px-4 text-gray-400 font-medium">Metric</th>
                  {selectedStrategies.map((strategyId, index) => (
                    <th key={strategyId} className="text-center py-3 px-4">
                      <div className="flex items-center justify-center gap-2">
                        <div
                          className="w-3 h-3 rounded-full"
                          style={{ backgroundColor: strategyStyles[strategyId]?.color || STRATEGY_COLOR_HEX[0] }}
                        />
                        <span className="text-xs text-gray-500 font-mono">
                          {getPatternIndicator(index)}
                        </span>
                        <span className="text-gray-200 font-medium">
                          {getStrategyDisplayName(strategyId).replace('Hierarchical Adaptive ', '')}
                        </span>
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {/* Strategy Cell Row */}
                <tr className="border-b border-slate-700/50">
                  <td className="py-3 px-4 text-gray-300">Strategy Cell</td>
                  {selectedStrategies.map((strategyId) => {
                    // v2 API returns history in DESC order (newest first at index 0)
                    const latestSnapshot = multiPerformanceData?.[strategyId]?.history?.[0]
                    const cell = latestSnapshot?.strategy_cell
                    return (
                      <td key={strategyId} className="py-3 px-4 text-center text-blue-400 font-medium">
                        {cell ?? 'N/A'}
                      </td>
                    )
                  })}
                </tr>
                {/* Trend State Row */}
                <tr className="border-b border-slate-700/50">
                  <td className="py-3 px-4 text-gray-300">Trend State</td>
                  {selectedStrategies.map((strategyId) => {
                    // v2 API returns history in DESC order (newest first at index 0)
                    const latestSnapshot = multiPerformanceData?.[strategyId]?.history?.[0]
                    const trend = latestSnapshot?.trend_state
                    return (
                      <td key={strategyId} className={`py-3 px-4 text-center font-medium ${
                        trend === 'BULLISH' ? 'text-green-400' :
                        trend === 'BEARISH' ? 'text-red-400' :
                        'text-yellow-400'
                      }`}>
                        {trend ?? 'N/A'}
                      </td>
                    )
                  })}
                </tr>
                {/* Volatility State Row */}
                <tr className="border-b border-slate-700/50">
                  <td className="py-3 px-4 text-gray-300">Volatility State</td>
                  {selectedStrategies.map((strategyId) => {
                    // v2 API returns history in DESC order (newest first at index 0)
                    const latestSnapshot = multiPerformanceData?.[strategyId]?.history?.[0]
                    const vol = latestSnapshot?.vol_state
                    return (
                      <td key={strategyId} className={`py-3 px-4 text-center font-medium ${
                        vol === 'LOW' ? 'text-green-400' :
                        vol === 'HIGH' ? 'text-red-400' :
                        'text-yellow-400'
                      }`}>
                        {vol ?? 'N/A'}
                      </td>
                    )
                  })}
                </tr>
              </tbody>
            </table>
          </div>
        ) : (
          // Single strategy card view
          <ResponsiveGrid
            columns={{ default: 1, sm: 3 }}
            gap="md"
          >
            <div className="bg-slate-700/50 rounded-lg p-3 sm:p-4">
              <ResponsiveText variant="small" className="text-gray-400 mb-1 block">
                Strategy Cell
              </ResponsiveText>
              <ResponsiveText variant="metric" className="text-blue-400">
                {regime?.cell ?? status?.regime?.cell ?? 'N/A'}
              </ResponsiveText>
            </div>

            <div className="bg-slate-700/50 rounded-lg p-3 sm:p-4">
              <ResponsiveText variant="small" className="text-gray-400 mb-1 block">
                Trend State
              </ResponsiveText>
              <ResponsiveText
                variant="metric"
                className={clsx(
                  (regime?.trend_state || status?.regime?.trend_state) === 'BULLISH' ? 'text-green-400' :
                  (regime?.trend_state || status?.regime?.trend_state) === 'BEARISH' ? 'text-red-400' :
                  'text-yellow-400'
                )}
              >
                {regime?.trend_state ?? status?.regime?.trend_state ?? 'N/A'}
              </ResponsiveText>
            </div>

            <div className="bg-slate-700/50 rounded-lg p-3 sm:p-4">
              <ResponsiveText variant="small" className="text-gray-400 mb-1 block">
                Volatility State
              </ResponsiveText>
              <ResponsiveText
                variant="metric"
                className={clsx(
                  (regime?.vol_state || status?.regime?.vol_state) === 'LOW' ? 'text-green-400' :
                  (regime?.vol_state || status?.regime?.vol_state) === 'HIGH' ? 'text-red-400' :
                  'text-yellow-400'
                )}
              >
                {regime?.vol_state ?? status?.regime?.vol_state ?? 'N/A'}
              </ResponsiveText>
            </div>
          </ResponsiveGrid>
        )}
      </ResponsiveCard>

      {/* 5. Decision Tree */}
      {indicators?.indicators && indicators.indicators.length > 0 && (() => {
        const getIndicator = (name: string) =>
          indicators.indicators?.find(i => i.name === name)

        const tNorm = getIndicator('t_norm')?.value
        const zScore = getIndicator('z_score')?.value
        const trendState = getIndicator('trend_state')?.signal
        const volState = getIndicator('vol_state')?.signal
        const smaFast = getIndicator('sma_fast')?.value
        const smaSlow = getIndicator('sma_slow')?.value
        const volCrushTriggered = getIndicator('vol_crush_triggered')?.value
        const bondSmaFast = getIndicator('bond_sma_fast')?.value
        const bondSmaSlow = getIndicator('bond_sma_slow')?.value
        const bondTrend = getIndicator('bond_trend')?.signal

        const trendStateStr = trendState ?? 'N/A'
        const volStateStr = volState ?? 'N/A'
        const bondTrendStr = bondTrend ?? 'N/A'

        const smaStructure = smaFast && smaSlow
          ? smaFast > smaSlow ? 'Bull (Fast > Slow)' : 'Bear (Fast < Slow)'
          : 'N/A'

        const isDefensiveCell = currentCell === 4 || currentCell === 5 || currentCell === 6

        return (
          <ResponsiveCard padding="md">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 mb-4">
              <ResponsiveText variant="h2" as="h3">
                Decision Tree
                <span className="text-xs sm:text-sm font-normal text-gray-400 ml-2">
                  ({indicators.symbol})
                </span>
              </ResponsiveText>
              {isComparisonMode && (
                <select
                  value={selectedDecisionTreeStrategy}
                  onChange={(e) => setSelectedDecisionTreeStrategy(e.target.value)}
                  className="px-3 py-1.5 bg-slate-700 rounded-lg text-sm text-gray-200 border border-slate-600 focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {selectedStrategies.map((strategyId) => (
                    <option key={strategyId} value={strategyId}>
                      {getStrategyDisplayName(strategyId).replace('Hierarchical Adaptive ', '')}
                    </option>
                  ))}
                </select>
              )}
            </div>

            <div className="space-y-3 sm:space-y-4">
              {/* Trend Classification Box */}
              <div className="bg-slate-700/50 rounded-lg p-3 sm:p-4">
                <h4 className="text-sm sm:text-md font-semibold mb-3 text-blue-400">TREND CLASSIFICATION</h4>
                <div className="space-y-2 text-xs sm:text-sm">
                  <div className="flex justify-between">
                    <span className="text-gray-400">T_norm (Kalman):</span>
                    <span className={clsx(
                      'font-bold',
                      typeof tNorm === 'number'
                        ? tNorm > 0.3 ? 'text-green-400'
                        : tNorm < -0.3 ? 'text-red-400'
                        : 'text-yellow-400'
                        : ''
                    )}>
                      {typeof tNorm === 'number' ? tNorm.toFixed(2) : 'N/A'}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-400">SMA Fast (40d):</span>
                    <span className="font-bold">{typeof smaFast === 'number' ? smaFast.toFixed(2) : 'N/A'}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-400">SMA Slow (140d):</span>
                    <span className="font-bold">{typeof smaSlow === 'number' ? smaSlow.toFixed(2) : 'N/A'}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-400">SMA Structure:</span>
                    <span className={clsx(
                      'font-bold',
                      smaStructure.startsWith('Bull') ? 'text-green-400'
                      : smaStructure.startsWith('Bear') ? 'text-red-400'
                      : ''
                    )}>
                      {smaStructure}
                    </span>
                  </div>
                  <div className="border-t border-slate-600 my-2"></div>
                  <div className="flex justify-between items-center">
                    <span className="text-gray-400">→ Trend State:</span>
                    <span className={clsx(
                      'text-base sm:text-xl font-bold',
                      trendStateStr === 'BullStrong' ? 'text-green-400'
                      : trendStateStr === 'BearStrong' ? 'text-red-400'
                      : 'text-yellow-400'
                    )}>
                      {trendStateStr || 'N/A'}
                    </span>
                  </div>
                </div>
              </div>

              {/* Volatility Classification Box */}
              <div className="bg-slate-700/50 rounded-lg p-3 sm:p-4">
                <h4 className="text-sm sm:text-md font-semibold mb-3 text-purple-400">VOLATILITY CLASSIFICATION</h4>
                <div className="space-y-2 text-xs sm:text-sm">
                  <div className="flex justify-between">
                    <span className="text-gray-400">Z-Score:</span>
                    <span className={clsx(
                      'font-bold',
                      typeof zScore === 'number'
                        ? zScore > 1.0 ? 'text-red-400'
                        : zScore < 0.2 ? 'text-green-400'
                        : 'text-yellow-400'
                        : ''
                    )}>
                      {typeof zScore === 'number' ? zScore.toFixed(2) : 'N/A'}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-400">Upper Threshold:</span>
                    <span className="font-bold">1.0</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-400">Lower Threshold:</span>
                    <span className="font-bold">0.2</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-400">Vol-Crush Override:</span>
                    <span className={clsx('font-bold', volCrushTriggered === 1 ? 'text-red-400' : 'text-gray-400')}>
                      {volCrushTriggered === 1 ? 'ACTIVE' : 'Inactive'}
                    </span>
                  </div>
                  <div className="border-t border-slate-600 my-2"></div>
                  <div className="flex justify-between items-center">
                    <span className="text-gray-400">→ Vol State:</span>
                    <span className={clsx(
                      'text-base sm:text-xl font-bold',
                      volStateStr === 'Low' ? 'text-green-400'
                      : volStateStr === 'High' ? 'text-red-400'
                      : 'text-yellow-400'
                    )}>
                      {volStateStr || 'N/A'}
                    </span>
                  </div>
                </div>
              </div>

              {/* Treasury Overlay Box */}
              {isDefensiveCell && bondSmaFast !== null && bondSmaFast !== undefined && bondSmaSlow !== null && bondSmaSlow !== undefined && (
                <div className="bg-slate-700/50 rounded-lg p-3 sm:p-4">
                  <h4 className="text-sm sm:text-md font-semibold mb-3 text-yellow-400">TREASURY OVERLAY (Active)</h4>
                  <div className="space-y-2 text-xs sm:text-sm">
                    <div className="flex justify-between">
                      <span className="text-gray-400">Bond SMA Fast (20d):</span>
                      <span className="font-bold">{typeof bondSmaFast === 'number' ? bondSmaFast.toFixed(2) : 'N/A'}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-gray-400">Bond SMA Slow (60d):</span>
                      <span className="font-bold">{typeof bondSmaSlow === 'number' ? bondSmaSlow.toFixed(2) : 'N/A'}</span>
                    </div>
                    <div className="border-t border-slate-600 my-2"></div>
                    <div className="flex justify-between items-center">
                      <span className="text-gray-400">→ Bond Trend:</span>
                      <span className={clsx(
                        'text-base sm:text-xl font-bold',
                        bondTrendStr === 'Bull' ? 'text-green-400'
                        : bondTrendStr === 'Bear' ? 'text-red-400'
                        : 'text-yellow-400'
                      )}>
                        {bondTrendStr || 'N/A'} → {bondTrendStr === 'Bull' ? 'TMF' : 'TMV'}
                      </span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </ResponsiveCard>
        )
      })()}

      {/* 6. Target Allocation */}
      {indicators?.target_allocation && (
        <ResponsiveCard padding="md">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 mb-4">
            <ResponsiveText variant="h2" as="h3" className="text-green-400">
              Target Allocation {currentCell ? `(Cell ${currentCell})` : ''}
            </ResponsiveText>
            {isComparisonMode && (
              <select
                value={selectedTargetAllocationStrategy}
                onChange={(e) => setSelectedTargetAllocationStrategy(e.target.value)}
                className="px-3 py-1.5 bg-slate-700 rounded-lg text-sm text-gray-200 border border-slate-600 focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                {selectedStrategies.map((strategyId) => (
                  <option key={strategyId} value={strategyId}>
                    {getStrategyDisplayName(strategyId).replace('Hierarchical Adaptive ', '')}
                  </option>
                ))}
              </select>
            )}
          </div>
          <div className="space-y-3">
            {Object.entries(indicators.target_allocation).map(([symbol, pct]) => {
              const percentage = typeof pct === 'number' ? pct : 0
              const barWidth = `${percentage}%`

              return (
                <div key={symbol}>
                  <div className="flex justify-between text-xs sm:text-sm mb-1">
                    <span className="text-gray-400">{symbol}:</span>
                    <span className="font-bold">{percentage.toFixed(0)}%</span>
                  </div>
                  <div className="w-full bg-slate-600 rounded-full h-2">
                    <div
                      className={clsx(
                        'h-2 rounded-full transition-all duration-300',
                        percentage > 0
                          ? symbol.includes('TQQQ') || symbol.includes('QQQ') ? 'bg-green-500'
                          : symbol.includes('PSQ') ? 'bg-red-500'
                          : symbol.includes('TMF') ? 'bg-blue-500'
                          : symbol.includes('TMV') ? 'bg-yellow-500'
                          : 'bg-gray-500'
                          : 'bg-transparent'
                      )}
                      style={{ width: barWidth }}
                    />
                  </div>
                </div>
              )
            })}
          </div>
        </ResponsiveCard>
      )}

      {/* 7. Execution Schedule - Admin Only */}
      {hasPermission('scheduler:control') && (status?.last_execution || status?.next_execution) && (
        <ResponsiveCard padding="md">
          <ResponsiveText variant="h2" as="h3" className="mb-4">
            Execution Schedule
          </ResponsiveText>

          <ResponsiveGrid
            columns={{ default: 1, sm: 2 }}
            gap="md"
          >
            {status.last_execution && (
              <div className="bg-slate-700/50 rounded-lg p-3 sm:p-4">
                <ResponsiveText variant="small" className="text-gray-400 mb-1 block">
                  Last Execution
                </ResponsiveText>
                <ResponsiveText variant="body" className="font-medium">
                  {new Date(status.last_execution).toLocaleString()}
                </ResponsiveText>
              </div>
            )}

            {status.next_execution && (
              <div className="bg-slate-700/50 rounded-lg p-3 sm:p-4">
                <ResponsiveText variant="small" className="text-gray-400 mb-1 block">
                  Next Execution
                </ResponsiveText>
                <ResponsiveText variant="body" className="font-medium">
                  {new Date(status.next_execution).toLocaleString()}
                </ResponsiveText>
              </div>
            )}
          </ResponsiveGrid>
        </ResponsiveCard>
      )}

      {/* Error Display */}
      {status?.error && (
        <div className="bg-red-900/30 border border-red-600 rounded-lg p-3 sm:p-4">
          <h3 className="text-red-400 font-medium mb-2 text-sm sm:text-base">Error</h3>
          <p className="text-red-300 text-xs sm:text-sm">{status.error}</p>
        </div>
      )}

      {/* 8. Scheduler Control - Admin Only */}
      {hasPermission('scheduler:control') && <SchedulerControl />}
    </div>
  )
}

export default DashboardV2
