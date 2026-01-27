/**
 * PerformanceV2 - Responsive Performance Page with Multi-Strategy Support
 *
 * Fully responsive performance dashboard with charts, metrics, and tables.
 * Supports comparison of up to 3 strategies with overlaid equity curves.
 *
 * @version 2.1.0
 * @part Responsive UI - Phase 4 + Multi-Strategy Comparison
 */

import { useQuery } from '@tanstack/react-query'
import { useState, useEffect, useRef, useMemo } from 'react'
import { performanceApi, performanceApiV2, DailyPerformanceData } from '../../api/client'
import { PerformanceDataV2 } from '../../hooks/useMultiStrategyData'
import { createChart, IChartApi, ISeriesApi, LineData, TickMarkType } from 'lightweight-charts'
import { ResponsiveCard, ResponsiveText, ResponsiveGrid, MetricCard } from '../../components/ui'
import { useIsMobileOrSmaller, useIsTablet } from '../../hooks/useMediaQuery'
import { useStrategy } from '../../contexts/StrategyContext'
import { StrategyMultiSelector } from '../../components/StrategyMultiSelector'
import { useMultiStrategyPerformanceDataV2 } from '../../hooks/useMultiStrategyData'
import {
  STRATEGY_COLORS,
  BASELINE_STYLE,
  STRATEGY_COLOR_HEX,
  getPatternIndicator,
  StrategyStyle,
} from '../../constants/strategyColors'

// Time range options
type TimeRange = '30d' | '90d' | 'ytd' | '1y' | 'all' | 'custom'

interface TimeRangeParams {
  days: number
  start_date?: string
}

function getTimeRangeParams(timeRange: TimeRange, customStartDate?: string, _customEndDate?: string): TimeRangeParams {
  const now = new Date()

  switch (timeRange) {
    case '30d':
      return { days: 30 }
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
    case 'custom':
      if (customStartDate) {
        return { days: 0, start_date: customStartDate }
      }
      return { days: 90 }
    default:
      return { days: 90 }
  }
}

function getTimeRangeLabel(timeRange: TimeRange): string {
  switch (timeRange) {
    case '30d': return '30-Day'
    case '90d': return '90-Day'
    case 'ytd': return 'YTD'
    case '1y': return '1-Year'
    case 'all': return 'All-Time'
    case 'custom': return 'Custom'
    default: return ''
  }
}

function calculatePeriodReturn(endCumReturn: number, startCumReturn: number): number {
  const startGrowth = 1 + startCumReturn / 100
  const endGrowth = 1 + endCumReturn / 100
  if (startGrowth === 0) return 0
  return (endGrowth / startGrowth - 1) * 100
}

function calculateAnnualizedReturn(periodReturnPct: number, calendarDays: number): number {
  if (calendarDays <= 0) return 0
  const periodReturn = periodReturnPct / 100
  const base = 1 + periodReturn
  if (base <= 0) return -100
  const annualized = Math.pow(base, 365 / calendarDays) - 1
  return annualized * 100
}

/**
 * Parse a YYYY-MM-DD date string as a local date (not UTC).
 * new Date("2026-01-23") creates midnight UTC which shifts to previous day in PST.
 * This function avoids that by parsing components directly.
 */
function parseLocalDate(dateStr: string): Date {
  const s = dateStr.slice(0, 10)
  const [y, m, d] = s.split('-').map(Number)
  return new Date(y, m - 1, d)
}

function formatTradingDate(dateStr: string): string {
  if (!dateStr) return '-'
  return parseLocalDate(dateStr).toLocaleDateString()
}

function calculateCalendarDays(history: Array<{ timestamp?: string; trading_date?: string }>): number {
  if (!history || history.length < 2) return history?.length || 0
  // v2 API returns history in DESC order (newest first), so:
  // history[0] = newest date, history[length-1] = oldest date
  const newestDate = (history[0].trading_date || history[0].timestamp)?.slice(0, 10)
  const oldestDate = (history[history.length - 1].trading_date || history[history.length - 1].timestamp)?.slice(0, 10)
  if (!newestDate || !oldestDate) return 0
  const start = parseLocalDate(oldestDate)
  const end = parseLocalDate(newestDate)
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
 * Deduplicate chart data by time, keeping the last value for each date.
 * Also sorts the data chronologically to satisfy lightweight-charts requirements.
 */
function deduplicateChartData<T extends { time: unknown; value: number }>(data: T[]): T[] {
  // Use a Map to keep only the last value for each date
  const dateMap = new Map<string, T>()
  for (const point of data) {
    dateMap.set(String(point.time), point)
  }
  // Convert back to array and sort by date
  return Array.from(dateMap.values()).sort((a, b) => String(a.time).localeCompare(String(b.time)))
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

// Comparison Row Component for Multi-Strategy Tables
interface ComparisonRowProps {
  label: string
  values: Record<string, number | null | undefined>
  strategyStyles: Record<string, StrategyStyle>
  format: 'percent' | 'currency' | 'number'
  higherIsBetter?: boolean
  baselineValue?: number | null
  strategyOrder: string[]
}

function ComparisonRow({
  label,
  values,
  strategyStyles: _strategyStyles,
  format,
  higherIsBetter = true,
  baselineValue,
  strategyOrder,
}: ComparisonRowProps) {
  // Note: _strategyStyles available for future color-coded cell backgrounds
  const bestId = findBestValue(values, higherIsBetter)

  return (
    <tr className="border-b border-slate-700/50">
      <td className="py-3 px-4 text-gray-300">{label}</td>
      {strategyOrder.map((strategyId) => {
        const value = values[strategyId]
        const isBest = strategyId === bestId
        return (
          <td
            key={strategyId}
            className={`py-3 px-4 text-center ${
              isBest ? 'font-bold' : ''
            } ${
              format === 'percent'
                ? value !== null && value !== undefined && value >= 0
                  ? 'text-green-400'
                  : 'text-red-400'
                : 'text-gray-200'
            }`}
          >
            {formatMetricValue(value, format)}
            {isBest && ' ★'}
          </td>
        )
      })}
      {baselineValue !== undefined && (
        <td className="py-3 px-4 text-center text-gray-400">
          {formatMetricValue(baselineValue, format)}
        </td>
      )}
    </tr>
  )
}

// Mobile Comparison Card Component
interface MobileComparisonCardProps {
  strategyName: string
  style: StrategyStyle
  metrics: {
    periodReturn?: number | null
    annualized?: number | null
    sharpe?: number | null
    maxDrawdown?: number | null
    totalEquity?: number | null
  }
  rank?: number
}

function MobileComparisonCard({
  strategyName,
  style,
  metrics,
  rank,
}: MobileComparisonCardProps) {
  return (
    <ResponsiveCard padding="md">
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div
              className="w-3 h-3 rounded-full"
              style={{ backgroundColor: style.color }}
            />
            <span className="text-gray-500 text-xs font-mono">{style.patternDesc}</span>
            <span className="font-medium text-white">{strategyName}</span>
          </div>
          {rank === 1 && (
            <span className="text-amber-400">★</span>
          )}
        </div>

        <div className="grid grid-cols-2 gap-3 text-sm">
          <div>
            <span className="text-gray-400 block">Total Equity</span>
            <span className="text-white font-medium">
              {formatMetricValue(metrics.totalEquity, 'currency')}
            </span>
          </div>
          <div>
            <span className="text-gray-400 block">Period Return</span>
            <span className={`font-medium ${
              (metrics.periodReturn ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'
            }`}>
              {formatMetricValue((metrics.periodReturn ?? 0) * 100, 'percent')}
            </span>
          </div>
          <div>
            <span className="text-gray-400 block">Annualized</span>
            <span className={`font-medium ${
              (metrics.annualized ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'
            }`}>
              {formatMetricValue(metrics.annualized, 'percent')}
            </span>
          </div>
          <div>
            <span className="text-gray-400 block">Sharpe</span>
            <span className="text-white font-medium">
              {formatMetricValue(metrics.sharpe, 'number')}
            </span>
          </div>
          <div className="col-span-2">
            <span className="text-gray-400 block">Max Drawdown</span>
            <span className="text-red-400 font-medium">
              {formatMetricValue(metrics.maxDrawdown, 'percent')}
            </span>
          </div>
        </div>
      </div>
    </ResponsiveCard>
  )
}

function PerformanceV2() {
  const isMobile = useIsMobileOrSmaller()
  const isTablet = useIsTablet()
  const {
    selectedStrategies,
    getStrategyDisplayName,
    getStyleForStrategyIndex,
    baselineStyle,
  } = useStrategy()
  const [mode, setMode] = useState('')
  const [timeRange, setTimeRange] = useState<TimeRange>('90d')
  const [showCustomModal, setShowCustomModal] = useState(false)
  const [customStartDate, setCustomStartDate] = useState('')
  const [customEndDate, setCustomEndDate] = useState('')

  // Single strategy dropdown for regime table in comparison mode
  const [regimeStrategyId, setRegimeStrategyId] = useState<string>(selectedStrategies[0] || '')
  // Single strategy dropdown for daily performance table in comparison mode
  const [dailyPerfStrategyId, setDailyPerfStrategyId] = useState<string>(selectedStrategies[0] || '')

  // Update regime strategy when selection changes
  useEffect(() => {
    if (selectedStrategies.length > 0 && !selectedStrategies.includes(regimeStrategyId)) {
      setRegimeStrategyId(selectedStrategies[0])
    }
    if (selectedStrategies.length > 0 && !selectedStrategies.includes(dailyPerfStrategyId)) {
      setDailyPerfStrategyId(selectedStrategies[0])
    }
  }, [selectedStrategies, regimeStrategyId, dailyPerfStrategyId])

  const queryParams = useMemo(() =>
    getTimeRangeParams(timeRange, customStartDate, customEndDate),
    [timeRange, customStartDate, customEndDate]
  )

  const chartContainerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  // Track series by strategy ID for multi-strategy support
  const strategySeriesRef = useRef<Map<string, ISeriesApi<'Line'>>>(new Map())
  const baselineSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  // Track chart readiness
  const [chartReady, setChartReady] = useState(false)

  // Determine if we're in comparison mode
  const isComparisonMode = selectedStrategies.length > 1

  // Single strategy data (for non-comparison mode) - v2 API
  const { data: singlePerformance, isLoading: isSingleLoading } = useQuery({
    queryKey: ['performance-v2', mode, timeRange, queryParams, selectedStrategies[0]],
    queryFn: async () => {
      const [dailyRes, historyRes] = await Promise.all([
        performanceApiV2.getDaily(selectedStrategies[0], { mode: mode || undefined }),
        performanceApiV2.getHistory(selectedStrategies[0], { mode: mode || undefined, days: queryParams.days || 365 }),
      ])
      return {
        data: dailyRes.data.data,
        history: historyRes.data.history,
        baseline: dailyRes.data.baseline,
        strategy_id: dailyRes.data.strategy_id,
        mode: dailyRes.data.mode,
        is_finalized: dailyRes.data.is_finalized,
        data_as_of: dailyRes.data.data_as_of,
      } as PerformanceDataV2
    },
    enabled: selectedStrategies.length === 1 && !!selectedStrategies[0],
  })

  // Equity curve data derived from v2 history (for chart compatibility)
  // NOTE: v2 API returns history in DESC order, chart needs ASC order
  const singleEquityCurve = useMemo(() => {
    if (!singlePerformance?.history) return null
    return {
      data: [...singlePerformance.history].reverse().map((snapshot) => ({
        time: snapshot.trading_date || snapshot.timestamp?.slice(0, 10) || '',
        value: snapshot.total_equity ?? 0,
        baseline_value: snapshot.baseline_value,
        baseline_return: snapshot.baseline_return,  // Cumulative baseline return (decimal)
      })),
    }
  }, [singlePerformance?.history])

  // Multi-strategy data (v2 API)
  const { data: multiPerformanceData, isLoading: isMultiLoading } = useMultiStrategyPerformanceDataV2(
    selectedStrategies,
    { mode: mode || undefined, days: queryParams.days || 365 },
    selectedStrategies.length > 1
  )

  // Regime breakdown for single strategy view (or dropdown selection in comparison)
  const targetRegimeStrategy = isComparisonMode ? regimeStrategyId : selectedStrategies[0]
  const { data: regimeBreakdown } = useQuery({
    queryKey: ['regimeBreakdown', mode, timeRange, queryParams, targetRegimeStrategy],
    queryFn: () => performanceApi.getRegimeBreakdown({
      mode: mode || undefined,
      days: queryParams.days,
      start_date: queryParams.start_date,
      strategy_id: targetRegimeStrategy,
    }).then(res => res.data),
    enabled: !!targetRegimeStrategy,
  })

  // Combined loading state
  const isLoading = isComparisonMode ? isMultiLoading : isSingleLoading

  // Get performance data based on mode
  const performance = isComparisonMode
    ? (multiPerformanceData?.[selectedStrategies[0]] ?? null)
    : singlePerformance

  // Period metrics calculation for single strategy
  const periodMetrics = useMemo(() => {
    if (!performance?.history || performance.history.length === 0) {
      return { periodReturn: 0, periodBaselineReturn: 0, periodAlpha: 0, annualizedReturn: 0, calendarDays: 0 }
    }

    // v2 API returns history in DESC order (newest first)
    // firstSnapshot = oldest date, lastSnapshot = newest date (chronologically)
    const firstSnapshot = performance.history[performance.history.length - 1]
    const lastSnapshot = performance.history[0]
    const calendarDays = calculateCalendarDays(performance.history)

    if (timeRange === 'all') {
      const cumReturn = lastSnapshot.cumulative_return ?? 0
      const baselineReturn = lastSnapshot.baseline_return ?? 0
      // v2 API returns decimals, calculateAnnualizedReturn expects percentages
      const annualizedReturn = calculateAnnualizedReturn(cumReturn * 100, calendarDays)
      return {
        periodReturn: cumReturn,
        periodBaselineReturn: baselineReturn,
        periodAlpha: cumReturn - baselineReturn,
        annualizedReturn,
        calendarDays
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

    return {
      periodReturn,
      periodBaselineReturn,
      periodAlpha: periodReturn - periodBaselineReturn,
      annualizedReturn,
      calendarDays
    }
  }, [performance?.history, timeRange])

  // Multi-strategy period metrics
  const multiPeriodMetrics = useMemo(() => {
    if (!isComparisonMode || !multiPerformanceData) return null

    const metricsMap: Record<string, {
      periodReturn: number
      annualized: number
      baselineReturn: number
      baselineAnnualized: number
      baselineMaxDrawdown: number
      baselineSharpe: number
      alpha: number
      calendarDays: number
    }> = {}

    selectedStrategies.forEach((strategyId) => {
      const perfData = multiPerformanceData?.[strategyId]
      if (!perfData?.history || perfData.history.length === 0) {
        metricsMap[strategyId] = { periodReturn: 0, annualized: 0, baselineReturn: 0, baselineAnnualized: 0, baselineMaxDrawdown: 0, baselineSharpe: 0, alpha: 0, calendarDays: 0 }
        return
      }

      // v2 API returns history in DESC order (newest first)
      // firstSnapshot = oldest date, lastSnapshot = newest date (chronologically)
      const firstSnapshot = perfData.history[perfData.history.length - 1]
      const lastSnapshot = perfData.history[0]
      const calendarDays = calculateCalendarDays(perfData.history)

      // Calculate baseline max drawdown from history
      let baselineMaxDrawdown = 0
      let baselinePeak = 0
      for (const snapshot of perfData.history) {
        const baselineValue = snapshot.baseline_value ?? 0
        if (baselineValue > baselinePeak) {
          baselinePeak = baselineValue
        }
        if (baselinePeak > 0) {
          const drawdown = ((baselineValue - baselinePeak) / baselinePeak) * 100
          if (drawdown < baselineMaxDrawdown) {
            baselineMaxDrawdown = drawdown
          }
        }
      }

      // Calculate baseline Sharpe ratio from daily returns
      const dailyBaselineReturns: number[] = []
      for (let i = 1; i < perfData.history.length; i++) {
        const prevReturn = perfData.history[i - 1].baseline_return ?? 0
        const currReturn = perfData.history[i].baseline_return ?? 0
        // Convert cumulative returns to daily return
        const prevGrowth = 1 + prevReturn / 100
        const currGrowth = 1 + currReturn / 100
        if (prevGrowth !== 0) {
          const dailyReturn = (currGrowth / prevGrowth - 1) * 100
          dailyBaselineReturns.push(dailyReturn)
        }
      }
      const baselineSharpe = calculateSharpeRatio(dailyBaselineReturns)

      if (timeRange === 'all') {
        const cumReturn = lastSnapshot.cumulative_return ?? 0
        const baselineReturn = lastSnapshot.baseline_return ?? 0
        // v2 API returns decimals, calculateAnnualizedReturn expects percentages
        const annualized = calculateAnnualizedReturn(cumReturn * 100, calendarDays)
        const baselineAnnualized = calculateAnnualizedReturn(baselineReturn * 100, calendarDays)
        metricsMap[strategyId] = {
          periodReturn: cumReturn,
          annualized,
          baselineReturn,
          baselineAnnualized,
          baselineMaxDrawdown,
          baselineSharpe,
          alpha: cumReturn - baselineReturn,
          calendarDays
        }
      } else {
        const periodReturn = calculatePeriodReturn(
          lastSnapshot.cumulative_return ?? 0,
          firstSnapshot.cumulative_return ?? 0
        )
        const baselineReturn = calculatePeriodReturn(
          lastSnapshot.baseline_return ?? 0,
          firstSnapshot.baseline_return ?? 0
        )
        // v2 API returns decimals, calculateAnnualizedReturn expects percentages
        const annualized = calculateAnnualizedReturn(periodReturn * 100, calendarDays)
        const baselineAnnualized = calculateAnnualizedReturn(baselineReturn * 100, calendarDays)
        metricsMap[strategyId] = {
          periodReturn,
          annualized,
          baselineReturn,
          baselineAnnualized,
          baselineMaxDrawdown,
          baselineSharpe,
          alpha: periodReturn - baselineReturn,
          calendarDays
        }
      }
    })

    return metricsMap
  }, [isComparisonMode, multiPerformanceData, selectedStrategies, timeRange])

  // Initialize chart
  useEffect(() => {
    if (!chartContainerRef.current) return
    if (chartRef.current) return

    const chartHeight = isMobile ? 250 : 300
    const initialWidth = chartContainerRef.current.clientWidth || 300

    chartRef.current = createChart(chartContainerRef.current, {
      layout: {
        background: { color: '#1e293b' },
        textColor: '#94a3b8',
      },
      grid: {
        vertLines: { color: '#334155' },
        horzLines: { color: '#334155' },
      },
      width: initialWidth,
      height: chartHeight,
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        tickMarkFormatter: (time: string | number, tickMarkType: TickMarkType) => {
          const date = typeof time === 'string' ? new Date(time) : new Date(time * 1000)
          const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
          const day = date.getDate()
          const month = months[date.getMonth()]
          const year = date.getFullYear()

          switch (tickMarkType) {
            case TickMarkType.Year:
              return year.toString()
            case TickMarkType.Month:
              return month
            case TickMarkType.DayOfMonth:
              return `${day} ${month}`
            default:
              return `${day} ${month}`
          }
        },
      },
      rightPriceScale: {
        borderColor: '#334155',
      },
      crosshair: {
        mode: 1,
        vertLine: { labelBackgroundColor: '#475569' },
        horzLine: { labelBackgroundColor: '#475569' },
      },
      localization: {
        priceFormatter: (price: number) => {
          const sign = price >= 0 ? '+' : ''
          return `${sign}${price.toFixed(2)}%`
        },
      },
    })

    const resizeObserver = new ResizeObserver((entries) => {
      if (chartContainerRef.current && chartRef.current) {
        const width = entries[0]?.contentRect.width || chartContainerRef.current.clientWidth
        if (width > 0) {
          chartRef.current.applyOptions({ width })
        }
      }
    })
    resizeObserver.observe(chartContainerRef.current)

    setChartReady(true)

    return () => {
      resizeObserver.disconnect()
      setChartReady(false)
      if (chartRef.current) {
        chartRef.current.remove()
        chartRef.current = null
        strategySeriesRef.current.clear()
        baselineSeriesRef.current = null
      }
    }
  }, [isLoading, isMobile])

  // Update chart data - Multi-strategy or single strategy
  useEffect(() => {
    if (!chartRef.current || !chartReady) return

    // Clear existing series
    strategySeriesRef.current.forEach((series) => {
      try {
        chartRef.current?.removeSeries(series)
      } catch {
        // Series might already be removed
      }
    })
    strategySeriesRef.current.clear()

    if (baselineSeriesRef.current) {
      try {
        chartRef.current.removeSeries(baselineSeriesRef.current)
      } catch {
        // Series might already be removed
      }
      baselineSeriesRef.current = null
    }

    const isAllTime = timeRange === 'all'
    const priceFormatter = isAllTime
      ? (price: number) => `$${price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
      : (price: number) => {
          const sign = price >= 0 ? '+' : ''
          return `${sign}${price.toFixed(2)}%`
        }

    chartRef.current.applyOptions({
      localization: { priceFormatter },
    })

    if (isComparisonMode && multiPerformanceData) {
      // Multi-strategy chart
      let baselineData: LineData[] = []

      selectedStrategies.forEach((strategyId, idx) => {
        const perfData = multiPerformanceData?.[strategyId]
        if (!perfData?.history || perfData.history.length === 0) return

        // v2 API returns history in DESC order, chart needs ASC order
        const historyAsc = [...perfData.history].reverse()

        const style = STRATEGY_COLORS[idx] || STRATEGY_COLORS[0]
        const series = chartRef.current!.addLineSeries({
          color: style.color,
          lineStyle: style.lineStyle,
          lineWidth: 2,
          priceFormat: { type: 'custom', formatter: priceFormatter },
        })

        const firstPoint = historyAsc[0]
        const firstEquity = firstPoint?.total_equity ?? 1

        if (isAllTime) {
          const chartData: LineData[] = historyAsc.map((point: DailyPerformanceData) => ({
            time: (point.trading_date || point.timestamp || '').slice(0, 10) as string,
            value: point.total_equity ?? 0,
          }))
          series.setData(deduplicateChartData(chartData))
        } else {
          const chartData: LineData[] = historyAsc.map((point: DailyPerformanceData) => ({
            time: (point.trading_date || point.timestamp || '').slice(0, 10) as string,
            value: firstEquity > 0 ? ((point.total_equity ?? firstEquity) / firstEquity - 1) * 100 : 0,
          }))
          series.setData(deduplicateChartData(chartData))
        }

        strategySeriesRef.current.set(strategyId, series)

        // Extract baseline data from first strategy's history
        // V2 API includes baseline_return (cumulative) and baseline_value per row
        if (idx === 0 && historyAsc.length > 0) {
          if (isAllTime) {
            // All-time view: show baseline equity values
            baselineData = historyAsc
              .filter((point: DailyPerformanceData) => point.baseline_value != null)
              .map((point: DailyPerformanceData) => ({
                time: (point.trading_date || '').slice(0, 10) as string,
                value: point.baseline_value ?? 0,
              }))
          } else {
            // Percentage view: use baseline_return directly (cumulative return in decimal)
            baselineData = historyAsc
              .filter((point: DailyPerformanceData) => point.baseline_return != null)
              .map((point: DailyPerformanceData) => ({
                time: (point.trading_date || '').slice(0, 10) as string,
                value: (point.baseline_return ?? 0) * 100,  // Convert decimal to percentage
              }))
          }
        }
      })

      // Add baseline series
      if (baselineData.length > 0) {
        baselineSeriesRef.current = chartRef.current.addLineSeries({
          color: BASELINE_STYLE.color,
          lineStyle: BASELINE_STYLE.lineStyle,
          lineWidth: 2,
          priceFormat: { type: 'custom', formatter: priceFormatter },
        })
        baselineSeriesRef.current.setData(baselineData)
      }
    } else if (!isComparisonMode && singleEquityCurve?.data && singleEquityCurve.data.length > 0) {
      // Single strategy chart
      const firstPoint = singleEquityCurve.data[0]
      const firstValue = firstPoint?.value ?? 1

      const series = chartRef.current.addLineSeries({
        color: '#3b82f6',
        lineWidth: 2,
        priceFormat: { type: 'custom', formatter: priceFormatter },
      })

      if (isAllTime) {
        const chartData: LineData[] = singleEquityCurve.data.map((point: { time: string; value: number }) => ({
          time: point.time as string,
          value: point.value,
        }))
        series.setData(deduplicateChartData(chartData))
      } else {
        const chartData: LineData[] = singleEquityCurve.data.map((point: { time: string; value: number }) => ({
          time: point.time as string,
          value: firstValue > 0 ? (point.value / firstValue - 1) * 100 : 0,
        }))
        series.setData(deduplicateChartData(chartData))
      }

      strategySeriesRef.current.set('portfolio', series)

      // Baseline series
      baselineSeriesRef.current = chartRef.current.addLineSeries({
        color: '#f59e0b',
        lineWidth: 2,
        lineStyle: 2,
        priceFormat: { type: 'custom', formatter: priceFormatter },
      })

      if (isAllTime) {
        // All-time view: show baseline equity values
        const baselineData: LineData[] = singleEquityCurve.data
          .filter((point: { time: string; baseline_value?: number }) => point.baseline_value != null)
          .map((point: { time: string; value: number; baseline_value?: number }) => ({
            time: point.time as string,
            value: point.baseline_value ?? 0,
          }))
        baselineSeriesRef.current.setData(deduplicateChartData(baselineData))
      } else {
        // Percentage view: use baseline_return directly (already cumulative return in decimal)
        const baselineData: LineData[] = singleEquityCurve.data
          .filter((point: { time: string; baseline_return?: number }) => point.baseline_return != null)
          .map((point: { time: string; value: number; baseline_return?: number }) => ({
            time: point.time as string,
            value: (point.baseline_return ?? 0) * 100,  // Convert decimal to percentage
          }))
        baselineSeriesRef.current.setData(deduplicateChartData(baselineData))
      }
    }

    chartRef.current?.timeScale().fitContent()
  }, [singleEquityCurve, multiPerformanceData, timeRange, chartReady, isComparisonMode, selectedStrategies, getStrategyDisplayName])

  // Build strategy styles map for comparison tables
  const strategyStyles = useMemo(() => {
    const styles: Record<string, StrategyStyle> = {}
    selectedStrategies.forEach((id, idx) => {
      styles[id] = getStyleForStrategyIndex(idx)
    })
    return styles
  }, [selectedStrategies, getStyleForStrategyIndex])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-400"></div>
      </div>
    )
  }

  return (
    <div className="space-y-4 sm:space-y-6">
      {/* Header & Controls */}
      <div className="flex flex-col gap-3">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <ResponsiveText variant="h1" as="h2" className="text-white">
            Performance
          </ResponsiveText>

          <div className="flex flex-col xs:flex-row gap-2 sm:gap-4">
            <select
              value={mode}
              onChange={(e) => setMode(e.target.value)}
              className="px-3 py-2 bg-slate-700 rounded-lg border border-slate-600 min-h-[44px]"
            >
              <option value="">All Modes</option>
              <option value="offline_mock">Paper Trading</option>
              <option value="online_live">Live Trading</option>
            </select>

            <select
              value={timeRange}
              onChange={(e) => {
                const value = e.target.value as TimeRange
                if (value === 'custom') {
                  setShowCustomModal(true)
                }
                setTimeRange(value)
              }}
              className="px-3 py-2 bg-slate-700 rounded-lg border border-slate-600 min-h-[44px]"
            >
              <option value="30d">Last 30 Days</option>
              <option value="90d">Last 90 Days</option>
              <option value="ytd">Year to Date</option>
              <option value="1y">Last Year</option>
              <option value="all">All Time</option>
              <option value="custom">Custom Range...</option>
            </select>
          </div>
        </div>

        {/* Strategy Multi-Selector */}
        <StrategyMultiSelector compact={isMobile} />
      </div>

      {/* Key Metrics - Comparison or Single View */}
      {isComparisonMode && multiPeriodMetrics ? (
        // Multi-Strategy Comparison Table
        isMobile ? (
          // Mobile: Stacked Cards
          <div className="space-y-3">
            {selectedStrategies.map((strategyId, idx) => {
              const perfData = multiPerformanceData?.[strategyId]
              const periodData = multiPeriodMetrics[strategyId]
              return (
                <MobileComparisonCard
                  key={strategyId}
                  strategyName={getStrategyDisplayName(strategyId)}
                  style={strategyStyles[strategyId]}
                  metrics={{
                    totalEquity: perfData?.data?.total_equity,
                    periodReturn: periodData?.periodReturn,
                    annualized: periodData?.annualized,
                    sharpe: perfData?.data?.sharpe_ratio,
                    maxDrawdown: perfData?.data?.max_drawdown != null
                      ? -Math.abs(perfData.data.max_drawdown)
                      : undefined,
                  }}
                  rank={idx === 0 ? 1 : undefined}
                />
              )
            })}
            {/* Baseline Card */}
            <MobileComparisonCard
              strategyName="Baseline (QQQ)"
              style={baselineStyle}
              metrics={{
                periodReturn: multiPeriodMetrics[selectedStrategies[0]]?.baselineReturn,
                annualized: multiPeriodMetrics[selectedStrategies[0]]?.baselineAnnualized,
                sharpe: multiPeriodMetrics[selectedStrategies[0]]?.baselineSharpe,
                maxDrawdown: multiPeriodMetrics[selectedStrategies[0]]?.baselineMaxDrawdown,
                // Show baseline (QQQ) total equity from latest snapshot
                // v2 API returns history in DESC order (newest first at index 0)
                totalEquity: multiPerformanceData?.[selectedStrategies[0]]?.history?.[0]?.baseline_value,
              }}
            />
          </div>
        ) : (
          // Desktop: Comparison Table
          <ResponsiveCard padding="md">
            <ResponsiveText variant="h2" as="h3" className="text-white mb-4">
              {getTimeRangeLabel(timeRange)} Performance Comparison
            </ResponsiveText>
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead className="text-sm text-gray-400 border-b border-slate-700">
                  <tr>
                    <th className="py-3 px-4">Metric</th>
                    {selectedStrategies.map((strategyId, idx) => (
                      <th key={strategyId} className="py-3 px-4 text-center">
                        <div className="flex items-center justify-center gap-2">
                          <div
                            className="w-3 h-3 rounded-full"
                            style={{ backgroundColor: STRATEGY_COLOR_HEX[idx as keyof typeof STRATEGY_COLOR_HEX] }}
                          />
                          <span className="text-gray-500 text-xs font-mono">{getPatternIndicator(idx)}</span>
                          <span style={{ color: STRATEGY_COLOR_HEX[idx as keyof typeof STRATEGY_COLOR_HEX] }}>
                            {getStrategyDisplayName(strategyId)}
                          </span>
                        </div>
                      </th>
                    ))}
                    <th className="py-3 px-4 text-center text-gray-400">
                      <div className="flex items-center justify-center gap-2">
                        <div
                          className="w-3 h-3 rounded-full"
                          style={{ backgroundColor: STRATEGY_COLOR_HEX.baseline }}
                        />
                        <span className="text-gray-500 text-xs font-mono">— —</span>
                        <span>Baseline</span>
                      </div>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <ComparisonRow
                    label="Total Equity"
                    values={Object.fromEntries(
                      selectedStrategies.map((id) => [id, multiPerformanceData?.[id]?.data?.total_equity])
                    )}
                    strategyStyles={strategyStyles}
                    format="currency"
                    higherIsBetter={true}
                    baselineValue={
                      // Show baseline (QQQ) total equity from latest snapshot
                      // v2 API returns history in DESC order (newest first at index 0)
                      multiPerformanceData?.[selectedStrategies[0]]?.history?.[0]?.baseline_value
                    }
                    strategyOrder={selectedStrategies}
                  />
                  <ComparisonRow
                    label={`${getTimeRangeLabel(timeRange)} Return`}
                    values={Object.fromEntries(
                      selectedStrategies.map((id) => [id, (multiPeriodMetrics[id]?.periodReturn ?? 0) * 100])
                    )}
                    strategyStyles={strategyStyles}
                    format="percent"
                    higherIsBetter={true}
                    baselineValue={(multiPeriodMetrics[selectedStrategies[0]]?.baselineReturn ?? 0) * 100}
                    strategyOrder={selectedStrategies}
                  />
                  <ComparisonRow
                    label="CAGR"
                    values={Object.fromEntries(
                      selectedStrategies.map((id) => [id, multiPeriodMetrics[id]?.annualized ?? 0])
                    )}
                    strategyStyles={strategyStyles}
                    format="percent"
                    higherIsBetter={true}
                    baselineValue={multiPeriodMetrics[selectedStrategies[0]]?.baselineAnnualized ?? 0}
                    strategyOrder={selectedStrategies}
                  />
                  <ComparisonRow
                    label="Sharpe Ratio"
                    values={Object.fromEntries(
                      selectedStrategies.map((id) => [id, multiPerformanceData?.[id]?.data?.sharpe_ratio])
                    )}
                    strategyStyles={strategyStyles}
                    format="number"
                    higherIsBetter={true}
                    baselineValue={multiPeriodMetrics[selectedStrategies[0]]?.baselineSharpe}
                    strategyOrder={selectedStrategies}
                  />
                  <ComparisonRow
                    label="Max Drawdown"
                    values={Object.fromEntries(
                      selectedStrategies.map((id) => {
                        const rawValue = multiPerformanceData?.[id]?.data?.max_drawdown
                        return [id, rawValue != null ? -Math.abs(rawValue) * 100 : null]
                      })
                    )}
                    strategyStyles={strategyStyles}
                    format="percent"
                    higherIsBetter={false}
                    baselineValue={(multiPeriodMetrics[selectedStrategies[0]]?.baselineMaxDrawdown ?? 0)}
                    strategyOrder={selectedStrategies}
                  />
                  <ComparisonRow
                    label="Alpha"
                    values={Object.fromEntries(
                      selectedStrategies.map((id) => [id, (multiPeriodMetrics[id]?.alpha ?? 0) * 100])
                    )}
                    strategyStyles={strategyStyles}
                    format="percent"
                    higherIsBetter={true}
                    baselineValue={0}
                    strategyOrder={selectedStrategies}
                  />
                </tbody>
              </table>
            </div>
          </ResponsiveCard>
        )
      ) : (
        // Single Strategy Metrics
        performance?.data && (
          <ResponsiveGrid columns={{ default: 2, md: 3, lg: 5 }} gap="md">
            <MetricCard
              label="Total Equity"
              value={performance.data.total_equity ?? 0}
              format="currency"
            />
            <MetricCard
              label={`${getTimeRangeLabel(timeRange)} Return`}
              value={periodMetrics.periodReturn * 100}
              format="percent"
            />
            <MetricCard
              label="CAGR"
              value={periodMetrics.annualizedReturn}
              format="percent"
            />
            <MetricCard
              label="Sharpe Ratio"
              value={performance.data.sharpe_ratio ?? 0}
              format="number"
            />
            <MetricCard
              label="Max Drawdown"
              value={performance.data.max_drawdown != null
                ? -Math.abs(performance.data.max_drawdown) * 100
                : 0}
              format="percent"
              className="col-span-2 md:col-span-1"
            />
          </ResponsiveGrid>
        )
      )}

      {/* Portfolio Holdings - Only show in single strategy mode */}
      {!isComparisonMode && performance?.data && (
        <ResponsiveCard padding="md">
          <ResponsiveText variant="h2" as="h3" className="text-white mb-4">
            Portfolio Holdings
          </ResponsiveText>
          <ResponsiveGrid columns={{ default: 2, md: 4, lg: 6 }} gap="md">
            {/* Cash */}
            <div className="bg-slate-700/50 rounded-lg p-3 sm:p-4">
              <div className="text-xs sm:text-sm text-gray-400 mb-1">Cash</div>
              <div className="text-lg sm:text-xl font-bold text-blue-400">
                ${(performance.data.cash ?? 0).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}
              </div>
              <div className="text-xs text-gray-500 mt-1">
                {(performance.data.cash_weight_pct ?? 0).toFixed(1)}%
              </div>
            </div>

            {/* Holdings */}
            {performance.data.holdings?.map((holding: {
              symbol: string
              quantity: number
              value: number
              weight_pct: number
            }) => (
              <div key={holding.symbol} className="bg-slate-700/50 rounded-lg p-3 sm:p-4">
                <div className="text-xs sm:text-sm text-gray-400 mb-1">{holding.symbol}</div>
                <div className="text-lg sm:text-xl font-bold text-green-400">
                  ${holding.value.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}
                </div>
                <div className="text-xs text-gray-500 mt-1">
                  {holding.quantity} shares ({holding.weight_pct.toFixed(1)}%)
                </div>
              </div>
            ))}

            {(!performance.data.holdings || performance.data.holdings.length === 0) && (
              <div className="col-span-full text-center text-gray-500 py-4">
                No positions currently held
              </div>
            )}
          </ResponsiveGrid>
        </ResponsiveCard>
      )}

      {/* Trade Statistics - Only show in single strategy mode */}
      {!isComparisonMode && performance?.data && (
        <ResponsiveGrid columns={{ default: 2, md: 4 }} gap="md">
          <MetricCard
            label="Total Trades"
            value={performance.data.total_trades ?? 0}
            format="number"
          />
          <MetricCard
            label="Win Rate"
            value={(performance.data.win_rate ?? 0) * 100}
            format="percent"
          />
          <MetricCard
            label="Winning Trades"
            value={performance.data.winning_trades ?? 0}
            format="number"
          />
          <MetricCard
            label="Losing Trades"
            value={performance.data.losing_trades ?? 0}
            format="number"
          />
        </ResponsiveGrid>
      )}

      {/* Equity Curve Chart */}
      <ResponsiveCard padding="md">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between mb-4 gap-2">
          <div>
            <ResponsiveText variant="h2" as="h3" className="text-white">
              {timeRange === 'all' ? 'Equity Curve' : `${getTimeRangeLabel(timeRange)} Performance`}
            </ResponsiveText>
            <ResponsiveText variant="small" className="text-gray-400">
              {timeRange === 'all'
                ? 'Absolute equity values over time'
                : 'Percentage return from start of period'}
            </ResponsiveText>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-xs sm:text-sm">
            {isComparisonMode ? (
              <>
                {selectedStrategies.map((strategyId, idx) => (
                  <div key={strategyId} className="flex items-center gap-2">
                    <div
                      className="w-4 h-0.5"
                      style={{
                        backgroundColor: STRATEGY_COLOR_HEX[idx as keyof typeof STRATEGY_COLOR_HEX],
                        borderStyle: idx === 1 ? 'dashed' : idx === 2 ? 'dotted' : 'solid',
                      }}
                    />
                    <span style={{ color: STRATEGY_COLOR_HEX[idx as keyof typeof STRATEGY_COLOR_HEX] }}>
                      {getStrategyDisplayName(strategyId)}
                    </span>
                  </div>
                ))}
                <div className="flex items-center gap-2">
                  <div className="w-4 h-0.5 border-t-2 border-dashed border-gray-400" />
                  <span className="text-gray-400">QQQ</span>
                </div>
              </>
            ) : (
              <>
                <div className="flex items-center gap-2">
                  <div className="w-4 h-0.5 bg-blue-500"></div>
                  <span className="text-gray-400">Portfolio</span>
                </div>
                <div className="flex items-center gap-2">
                  <div className="w-4 h-0.5 bg-amber-500" style={{ borderTop: '2px dashed #f59e0b' }}></div>
                  <span className="text-gray-400">QQQ</span>
                </div>
              </>
            )}
          </div>
        </div>
        <div ref={chartContainerRef} className="w-full" />
      </ResponsiveCard>

      {/* Regime Performance */}
      {regimeBreakdown && (() => {
        const totalDays = regimeBreakdown.regimes?.reduce((sum: number, r: { days?: number }) => sum + (r.days ?? 0), 0) ?? 1

        return (
          <ResponsiveCard padding="md">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between mb-4 gap-2">
              <ResponsiveText variant="h2" as="h3" className="text-white">
                Performance by Regime
              </ResponsiveText>
              {/* Strategy dropdown in comparison mode */}
              {isComparisonMode && (
                <select
                  value={regimeStrategyId}
                  onChange={(e) => setRegimeStrategyId(e.target.value)}
                  className="px-3 py-2 bg-slate-700 rounded-lg border border-slate-600 min-h-[44px] text-sm"
                >
                  {selectedStrategies.map((id) => (
                    <option key={id} value={id}>
                      {getStrategyDisplayName(id)}
                    </option>
                  ))}
                </select>
              )}
            </div>

            {isMobile ? (
              // Mobile Card View
              <div className="space-y-3">
                {regimeBreakdown.regimes?.map((regime: {
                  cell: number
                  trend_state: string
                  vol_state: string
                  total_return: number
                  days?: number
                }) => {
                  const tradingDays = regime.days ?? 0
                  const pctOfTime = totalDays > 0 ? (tradingDays / totalDays) * 100 : 0
                  const calendarDays = Math.round(tradingDays * (365 / 252))
                  const annualizedReturn = calculateAnnualizedReturn(regime.total_return, calendarDays)

                  return (
                    <div key={regime.cell} className="bg-slate-700/50 rounded-lg p-4">
                      <div className="flex items-center justify-between mb-3">
                        <span className="px-2 py-1 bg-slate-600 rounded font-mono">
                          Cell {regime.cell}
                        </span>
                        <span className="text-gray-400 text-sm">
                          {tradingDays} days ({pctOfTime.toFixed(1)}%)
                        </span>
                      </div>
                      <div className="grid grid-cols-2 gap-3 text-sm">
                        <div>
                          <span className="text-gray-400 block">Trend</span>
                          <span className={
                            regime.trend_state === 'BULLISH' ? 'text-green-400' :
                            regime.trend_state === 'BEARISH' ? 'text-red-400' : 'text-yellow-400'
                          }>
                            {regime.trend_state}
                          </span>
                        </div>
                        <div>
                          <span className="text-gray-400 block">Volatility</span>
                          <span className={
                            regime.vol_state === 'LOW' ? 'text-green-400' :
                            regime.vol_state === 'HIGH' ? 'text-red-400' : 'text-yellow-400'
                          }>
                            {regime.vol_state}
                          </span>
                        </div>
                        <div>
                          <span className="text-gray-400 block">Return</span>
                          <span className={regime.total_return >= 0 ? 'text-green-400' : 'text-red-400'}>
                            {regime.total_return >= 0 ? '+' : ''}{regime.total_return.toFixed(2)}%
                          </span>
                        </div>
                        <div>
                          <span className="text-gray-400 block">Annualized</span>
                          <span className={annualizedReturn >= 0 ? 'text-green-400' : 'text-red-400'}>
                            {annualizedReturn >= 0 ? '+' : ''}{annualizedReturn.toFixed(2)}%
                          </span>
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            ) : (
              // Desktop Table View
              <div className="overflow-x-auto">
                <table className="w-full text-left">
                  <thead className="text-sm text-gray-400 border-b border-slate-700">
                    <tr>
                      <th className="pb-3">Cell</th>
                      <th className="pb-3">Trend</th>
                      <th className="pb-3">Volatility</th>
                      <th className="pb-3">Return %</th>
                      <th className="pb-3">Annualized</th>
                      <th className="pb-3">Days</th>
                      <th className="pb-3">% of Time</th>
                    </tr>
                  </thead>
                  <tbody>
                    {regimeBreakdown.regimes?.map((regime: {
                      cell: number
                      trend_state: string
                      vol_state: string
                      total_return: number
                      days?: number
                    }) => {
                      const tradingDays = regime.days ?? 0
                      const pctOfTime = totalDays > 0 ? (tradingDays / totalDays) * 100 : 0
                      const calendarDays = Math.round(tradingDays * (365 / 252))
                      const annualizedReturn = calculateAnnualizedReturn(regime.total_return, calendarDays)

                      return (
                        <tr key={regime.cell} className="border-b border-slate-700/50">
                          <td className="py-3">
                            <span className="px-2 py-1 bg-slate-700 rounded font-mono">
                              {regime.cell}
                            </span>
                          </td>
                          <td className={`py-3 ${
                            regime.trend_state === 'BULLISH' ? 'text-green-400' :
                            regime.trend_state === 'BEARISH' ? 'text-red-400' : 'text-yellow-400'
                          }`}>
                            {regime.trend_state}
                          </td>
                          <td className={`py-3 ${
                            regime.vol_state === 'LOW' ? 'text-green-400' :
                            regime.vol_state === 'HIGH' ? 'text-red-400' : 'text-yellow-400'
                          }`}>
                            {regime.vol_state}
                          </td>
                          <td className={`py-3 ${
                            regime.total_return >= 0 ? 'text-green-400' : 'text-red-400'
                          }`}>
                            {regime.total_return >= 0 ? '+' : ''}{regime.total_return.toFixed(2)}%
                          </td>
                          <td className={`py-3 ${
                            annualizedReturn >= 0 ? 'text-green-400' : 'text-red-400'
                          }`}>
                            {annualizedReturn >= 0 ? '+' : ''}{annualizedReturn.toFixed(2)}%
                          </td>
                          <td className="py-3 text-gray-300">{tradingDays}</td>
                          <td className="py-3 text-gray-300">{pctOfTime.toFixed(1)}%</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </ResponsiveCard>
        )
      })()}

      {/* Daily Performance History - Works in both single and comparison modes */}
      {(() => {
        // Get the appropriate performance data based on mode
        const dailyPerfData = isComparisonMode
          ? multiPerformanceData?.[dailyPerfStrategyId]
          : performance
        
        if (!dailyPerfData?.history || dailyPerfData.history.length === 0) return null
        // Deduplicate by date (use trading_date for v2, fallback to timestamp for v1)
        const historyByDate = new Map<string, typeof dailyPerfData.history[0]>()
        for (const snapshot of dailyPerfData.history) {
          const dateStr = snapshot.trading_date || snapshot.timestamp || ''
          const dateKey = dateStr ? formatTradingDate(dateStr) : ''
          if (dateKey) historyByDate.set(dateKey, snapshot)
        }
        const deduplicatedHistory = Array.from(historyByDate.values())
          .sort((a, b) => {
            const dateA = parseLocalDate(a.trading_date || a.timestamp || '').getTime()
            const dateB = parseLocalDate(b.trading_date || b.timestamp || '').getTime()
            return dateA - dateB // ASC order for correct daily return calculation
          })

        // Recalculate daily returns
        const dailyReturnsMap = new Map<string, number>()
        for (let i = 0; i < deduplicatedHistory.length; i++) {
          const current = deduplicatedHistory[i]
          const currentDateStr = current.trading_date || current.timestamp || ''
          const currentDateKey = currentDateStr ? formatTradingDate(currentDateStr) : ''
          if (i === 0) {
            dailyReturnsMap.set(currentDateKey, current.daily_return ?? 0)
          } else {
            const previous = deduplicatedHistory[i - 1]
            const prevEquity = previous.total_equity ?? 0
            const currEquity = current.total_equity ?? 0
            if (prevEquity > 0) {
              const trueDaily = ((currEquity - prevEquity) / prevEquity) * 100
              dailyReturnsMap.set(currentDateKey, trueDaily)
            } else {
              dailyReturnsMap.set(currentDateKey, 0)
            }
          }
        }

        return (
          <ResponsiveCard padding="md">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between mb-4 gap-2">
              <ResponsiveText variant="h2" as="h3" className="text-white">
                Daily Performance
              </ResponsiveText>
              {/* Strategy dropdown in comparison mode */}
              {isComparisonMode && (
                <select
                  value={dailyPerfStrategyId}
                  onChange={(e) => setDailyPerfStrategyId(e.target.value)}
                  className="px-3 py-2 bg-slate-700 rounded-lg border border-slate-600 min-h-[44px] text-sm"
                >
                  {selectedStrategies.map((id) => (
                    <option key={id} value={id}>
                      {getStrategyDisplayName(id)}
                    </option>
                  ))}
                </select>
              )}
            </div>

            {isMobile ? (
              // Mobile: Simplified card view with key metrics only
              <div className="space-y-2 max-h-96 overflow-y-auto">
                {deduplicatedHistory.slice().reverse().slice(0, 30).map((snapshot, idx) => {
                  const dateStr = snapshot.trading_date || snapshot.timestamp || ''
                  const dateKey = dateStr ? formatTradingDate(dateStr) : ''
                  const trueDailyReturn = dailyReturnsMap.get(dateKey) ?? 0
                  const alpha = (snapshot.cumulative_return ?? 0) - (snapshot.baseline_return ?? 0)

                  return (
                    <div key={idx} className="bg-slate-700/50 rounded-lg p-3 flex items-center justify-between">
                      <div>
                        <div className="text-sm text-white">
                          {dateStr ? formatTradingDate(dateStr) : '-'}
                        </div>
                        <div className="text-xs text-gray-400">
                          ${snapshot.total_equity?.toLocaleString(undefined, {minimumFractionDigits: 0, maximumFractionDigits: 0})}
                        </div>
                      </div>
                      <div className="text-right">
                        <div className={`text-sm font-medium ${
                          trueDailyReturn >= 0 ? 'text-green-400' : 'text-red-400'
                        }`}>
                          {trueDailyReturn >= 0 ? '+' : ''}{trueDailyReturn.toFixed(2)}%
                        </div>
                        <div className={`text-xs ${
                          alpha >= 0 ? 'text-green-400/70' : 'text-red-400/70'
                        }`}>
                          α: {alpha >= 0 ? '+' : ''}{(alpha * 100).toFixed(2)}%
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            ) : (
              // Desktop: Full table
              <div className="overflow-x-auto max-h-96">
                <table className="w-full text-left text-sm">
                  <thead className="text-xs text-gray-400 border-b border-slate-700 sticky top-0 bg-slate-800">
                    <tr>
                      <th className="pb-3 pr-4">Date</th>
                      <th className="pb-3 pr-4">Regime</th>
                      <th className="pb-3 pr-4">Equity</th>
                      {!isTablet && <th className="pb-3 pr-4">Cash</th>}
                      <th className="pb-3 pr-4">Day %</th>
                      <th className="pb-3 pr-4">Cum %</th>
                      {!isTablet && <th className="pb-3 pr-4 text-amber-400">Baseline</th>}
                      <th className="pb-3 pr-4">Alpha</th>
                      <th className="pb-3">DD %</th>
                    </tr>
                  </thead>
                  <tbody>
                    {deduplicatedHistory.slice().reverse().map((snapshot, idx) => {
                      const dateStr = snapshot.trading_date || snapshot.timestamp || ''
                      const dateKey = dateStr ? formatTradingDate(dateStr) : ''
                      const trueDailyReturn = dailyReturnsMap.get(dateKey) ?? 0
                      const alpha = (snapshot.cumulative_return ?? 0) - (snapshot.baseline_return ?? 0)

                      return (
                        <tr key={idx} className="border-b border-slate-700/50">
                          <td className="py-2 pr-4 whitespace-nowrap">
                            {dateStr ? formatTradingDate(dateStr) : '-'}
                          </td>
                          <td className="py-2 pr-4">
                            <span className="px-2 py-1 bg-slate-700 rounded text-xs whitespace-nowrap">
                              {snapshot.trend_state && snapshot.vol_state
                                ? `${snapshot.trend_state.slice(0, 4)} + ${snapshot.vol_state}`
                                : snapshot.strategy_cell
                                  ? `Cell ${snapshot.strategy_cell}`
                                  : '-'}
                            </span>
                          </td>
                          <td className="py-2 pr-4 font-medium">
                            ${snapshot.total_equity?.toLocaleString(undefined, {minimumFractionDigits: 0, maximumFractionDigits: 0})}
                          </td>
                          {!isTablet && (
                            <td className="py-2 pr-4 text-blue-400">
                              ${(snapshot.cash ?? 0).toLocaleString(undefined, {minimumFractionDigits: 0, maximumFractionDigits: 0})}
                            </td>
                          )}
                          <td className={`py-2 pr-4 ${
                            trueDailyReturn >= 0 ? 'text-green-400' : 'text-red-400'
                          }`}>
                            {trueDailyReturn.toFixed(2)}%
                          </td>
                          <td className={`py-2 pr-4 ${
                            (snapshot.cumulative_return ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'
                          }`}>
                            {((snapshot.cumulative_return ?? 0) * 100).toFixed(2)}%
                          </td>
                          {!isTablet && (
                            <td className={`py-2 pr-4 ${
                              (snapshot.baseline_return ?? 0) >= 0 ? 'text-amber-400' : 'text-amber-600'
                            }`}>
                              {snapshot.baseline_return != null
                                ? `${(snapshot.baseline_return * 100).toFixed(2)}%`
                                : '-'}
                            </td>
                          )}
                          <td className={`py-2 pr-4 font-medium ${
                            alpha >= 0 ? 'text-green-400' : 'text-red-400'
                          }`}>
                            {snapshot.baseline_return != null
                              ? `${alpha >= 0 ? '+' : ''}${(alpha * 100).toFixed(2)}%`
                              : '-'}
                          </td>
                          <td className="py-2 text-red-400">
                            {((snapshot.drawdown ?? 0)).toFixed(2)}%
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </ResponsiveCard>
        )
      })()}

      {/* Custom Date Range Modal */}
      {showCustomModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <ResponsiveCard padding="md" className="w-full max-w-md">
            <ResponsiveText variant="h2" as="h3" className="text-white mb-4">
              Select Custom Date Range
            </ResponsiveText>

            <div className="space-y-4">
              <div>
                <label className="block text-sm text-gray-400 mb-1">Start Date</label>
                <input
                  type="date"
                  value={customStartDate}
                  onChange={(e) => setCustomStartDate(e.target.value)}
                  className="w-full px-3 py-2 bg-slate-700 rounded-lg border border-slate-600 min-h-[44px]"
                />
              </div>

              <div>
                <label className="block text-sm text-gray-400 mb-1">End Date (optional)</label>
                <input
                  type="date"
                  value={customEndDate}
                  onChange={(e) => setCustomEndDate(e.target.value)}
                  className="w-full px-3 py-2 bg-slate-700 rounded-lg border border-slate-600 min-h-[44px]"
                  placeholder="Leave empty for today"
                />
              </div>
            </div>

            <div className="flex gap-3 mt-6">
              <button
                onClick={() => {
                  setShowCustomModal(false)
                  if (!customStartDate) {
                    setTimeRange('90d')
                  }
                }}
                className="flex-1 px-4 py-2 bg-slate-600 hover:bg-slate-500 rounded-lg transition-colors min-h-[44px]"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  setShowCustomModal(false)
                }}
                disabled={!customStartDate}
                className="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition-colors min-h-[44px]"
              >
                Apply
              </button>
            </div>
          </ResponsiveCard>
        </div>
      )}
    </div>
  )
}

export default PerformanceV2
