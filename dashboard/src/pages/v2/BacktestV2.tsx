/**
 * BacktestV2 - Multi-Strategy Comparison Backtest Dashboard
 *
 * Displays backtest results with support for comparing up to 3 strategies.
 * Features:
 * - Multi-strategy selection with colorblind-friendly patterns
 * - Overlaid equity curves for comparison
 * - Side-by-side metrics tables
 * - Single-strategy view preserved when only 1 selected
 * - Bidirectional date-chart synchronization
 * - Admin-only strategy config viewer
 *
 * @version 2.0.0
 * @part Multi-Strategy Comparison UI - Phase 2
 */

import { useQuery } from '@tanstack/react-query'
import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { ChevronDown, ChevronUp, Settings, Calendar, TrendingUp, BarChart3, Trophy, Medal } from 'lucide-react'
import { backtestApi } from '../../api/client'
import { createChart, IChartApi, ISeriesApi, LineData, TickMarkType, Time, LineStyle } from 'lightweight-charts'
import { ResponsiveCard, ResponsiveText, ResponsiveGrid, MetricCard } from '../../components/ui'
import { useIsMobileOrSmaller, useIsTablet } from '../../hooks/useMediaQuery'
import { useAuth } from '../../contexts/AuthContext'
import { useStrategy } from '../../contexts/StrategyContext'
import StrategyMultiSelector from '../../components/StrategyMultiSelector'
import { useMultiStrategyBacktestData, findBestStrategy } from '../../hooks/useMultiStrategyData'
import { BASELINE_STYLE, type StrategyStyle } from '../../constants/strategyColors'

// Helper functions
function formatPercent(value: number | null | undefined, decimals = 2): string {
  if (value == null) return '-'
  const sign = value >= 0 ? '+' : ''
  return `${sign}${value.toFixed(decimals)}%`
}

function formatCurrency(value: number | null | undefined): string {
  if (value == null) return '-'
  return `$${value.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
}

function formatNumber(value: number | null | undefined, decimals = 2): string {
  if (value == null) return '-'
  return value.toFixed(decimals)
}

// Comparison row component for metrics tables
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
  strategyStyles,
  format,
  higherIsBetter = true,
  baselineValue,
  strategyOrder
}: ComparisonRowProps) {
  const formatValue = (val: number | null | undefined) => {
    switch (format) {
      case 'percent': return formatPercent(val)
      case 'currency': return formatCurrency(val)
      case 'number': return formatNumber(val)
      default: return String(val ?? '-')
    }
  }

  // Find best strategy for this metric
  const numericValues: Record<string, number | undefined> = {}
  for (const [key, val] of Object.entries(values)) {
    numericValues[key] = val ?? undefined
  }
  const bestStrategy = findBestStrategy(numericValues, higherIsBetter)

  return (
    <tr className="border-b border-slate-700/50">
      <td className="py-3 text-gray-400">{label}</td>
      {strategyOrder.map((strategyId) => {
        const style = strategyStyles[strategyId]
        const value = values[strategyId]
        const isBest = bestStrategy === strategyId && Object.keys(values).length > 1
        const isPositive = value != null && value >= 0

        return (
          <td
            key={strategyId}
            className={`py-3 font-medium ${isPositive ? 'text-green-400' : 'text-red-400'}`}
          >
            <div className="flex items-center gap-2">
              <span
                className="w-3 h-3 rounded-full flex-shrink-0"
                style={{ backgroundColor: style?.color || '#6b7280' }}
              />
              <span>{formatValue(value)}</span>
              {isBest && <Trophy className="w-4 h-4 text-amber-400" />}
            </div>
          </td>
        )
      })}
      {baselineValue !== undefined && (
        <td className={`py-3 ${(baselineValue ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
          <div className="flex items-center gap-2">
            <span
              className="w-3 h-3 rounded-full flex-shrink-0"
              style={{ backgroundColor: BASELINE_STYLE.color }}
            />
            <span>{formatValue(baselineValue)}</span>
          </div>
        </td>
      )}
    </tr>
  )
}

// Mobile comparison card for smaller screens
interface MobileComparisonCardProps {
  strategyName: string
  style: StrategyStyle
  metrics: {
    totalReturn?: number | null
    cagr?: number | null
    sharpe?: number | null
    maxDrawdown?: number | null
    alpha?: number | null
  }
  rank?: number
}

function MobileComparisonCard({ strategyName, style, metrics, rank }: MobileComparisonCardProps) {
  return (
    <div className="bg-slate-700/50 rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span
            className="w-4 h-4 rounded-full"
            style={{ backgroundColor: style.color }}
          />
          <span className="font-medium text-white">{strategyName}</span>
        </div>
        {rank && rank <= 3 && (
          <div className="flex items-center gap-1">
            {rank === 1 && <Trophy className="w-4 h-4 text-amber-400" />}
            {rank === 2 && <Medal className="w-4 h-4 text-gray-300" />}
            {rank === 3 && <Medal className="w-4 h-4 text-amber-600" />}
          </div>
        )}
      </div>
      <div className="grid grid-cols-2 gap-3 text-sm">
        <div>
          <span className="text-gray-400 block">Total Return</span>
          <span className={(metrics.totalReturn ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}>
            {formatPercent(metrics.totalReturn)}
          </span>
        </div>
        <div>
          <span className="text-gray-400 block">CAGR</span>
          <span className={(metrics.cagr ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}>
            {formatPercent(metrics.cagr)}
          </span>
        </div>
        <div>
          <span className="text-gray-400 block">Sharpe</span>
          <span className="text-gray-200">{formatNumber(metrics.sharpe)}</span>
        </div>
        <div>
          <span className="text-gray-400 block">Max DD</span>
          <span className="text-red-400">{formatPercent(metrics.maxDrawdown)}</span>
        </div>
        <div className="col-span-2">
          <span className="text-gray-400 block">Alpha vs QQQ</span>
          <span className={(metrics.alpha ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}>
            {formatPercent(metrics.alpha)}
          </span>
        </div>
      </div>
    </div>
  )
}

function BacktestV2() {
  const isMobile = useIsMobileOrSmaller()
  const isTablet = useIsTablet()
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const {
    selectedStrategies,
    getColorForStrategy,
    baselineStyle,
    loadStrategiesFromUrl,
    updateUrlWithStrategies
  } = useStrategy()

  // Load strategies from URL on mount
  useEffect(() => {
    loadStrategiesFromUrl()
  }, [loadStrategiesFromUrl])

  // Update URL when strategies change
  useEffect(() => {
    updateUrlWithStrategies()
  }, [selectedStrategies, updateUrlWithStrategies])

  // Determine if we're in comparison mode (more than 1 strategy selected)
  const isComparisonMode = selectedStrategies.length > 1

  // State for date range filtering (actual API filter - only changes on explicit user input)
  const [filterStartDate, setFilterStartDate] = useState<string>('')
  const [filterEndDate, setFilterEndDate] = useState<string>('')
  // State for chart view range (visual only - doesn't trigger refetch)
  const [viewStartDate, setViewStartDate] = useState<string>('')
  const [viewEndDate, setViewEndDate] = useState<string>('')
  // Flag to track if date change came from chart interaction
  const isChartInteractionRef = useRef(false)
  // Flag to track if user is explicitly typing dates (prevents chart from overwriting)
  const isUserTypingDateRef = useRef(false)
  const [showConfigPane, setShowConfigPane] = useState(false)
  const [displayMode, setDisplayMode] = useState<'percentage' | 'absolute'>('percentage')
  // Base index for percentage calculations - when panning, this updates to the first visible point
  const [percentageBaseIndex, setPercentageBaseIndex] = useState<number>(0)
  // Strategy selector for regime table in comparison mode
  const [regimeTableStrategy, setRegimeTableStrategy] = useState<string>(selectedStrategies[0] || '')

  // Update regime table strategy when selected strategies change
  useEffect(() => {
    if (selectedStrategies.length > 0 && !selectedStrategies.includes(regimeTableStrategy)) {
      setRegimeTableStrategy(selectedStrategies[0])
    }
  }, [selectedStrategies, regimeTableStrategy])

  // Chart refs
  const chartContainerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  // Store series refs by strategy ID
  const strategySeriesRefs = useRef<Map<string, ISeriesApi<'Line'>>>(new Map())
  const baselineSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const [chartReady, setChartReady] = useState(false)
  const visibleRangeHandlerRef = useRef<(() => void) | null>(null)
  const recalcDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const recalcFnRef = useRef<(() => void) | null>(null)
  const isInitialLoadRef = useRef(true)

  // Fetch multi-strategy backtest data in parallel
  const {
    data: multiStrategyData,
    isLoading: isMultiLoading,
    errors: _errors
  } = useMultiStrategyBacktestData(
    selectedStrategies,
    {
      start_date: filterStartDate || undefined,
      end_date: filterEndDate || undefined,
    },
    selectedStrategies.length > 0
  )

  // Get primary strategy data for single-strategy view
  const primaryStrategyId = selectedStrategies[0]
  const primaryData = primaryStrategyId ? multiStrategyData[primaryStrategyId] : undefined

  // Fetch regime breakdown for the selected strategy in regime table
  const { data: regimeData } = useQuery({
    queryKey: ['backtest-regime', filterStartDate, filterEndDate, regimeTableStrategy],
    queryFn: () => backtestApi.getRegimeBreakdown({
      start_date: filterStartDate || undefined,
      end_date: filterEndDate || undefined,
      strategy_id: regimeTableStrategy,
    }).then(res => res.data),
    enabled: !!regimeTableStrategy,
  })

  // Fetch config (admin only) - show for first selected strategy
  const { data: configData } = useQuery({
    queryKey: ['backtest-config', primaryStrategyId],
    queryFn: () => backtestApi.getConfig({ strategy_id: primaryStrategyId }).then(res => res.data),
    enabled: isAdmin && !!primaryStrategyId,
  })

  // Get date bounds from the first strategy with data
  const dateBounds = useMemo(() => {
    for (const strategyId of selectedStrategies) {
      const data = multiStrategyData[strategyId]
      if (data?.summary?.start_date && data?.summary?.end_date) {
        return { min: data.summary.start_date, max: data.summary.end_date }
      }
      if (data?.timeseries && data.timeseries.length > 0) {
        const dates = data.timeseries.map(d => d.date).sort()
        return { min: dates[0], max: dates[dates.length - 1] }
      }
    }
    return { min: '', max: '' }
  }, [multiStrategyData, selectedStrategies])

  // Initialize view dates to full backtest range when data loads
  useEffect(() => {
    if (dateBounds.min && dateBounds.max && !viewStartDate && !viewEndDate) {
      setViewStartDate(dateBounds.min)
      setViewEndDate(dateBounds.max)
      setTimeout(() => {
        isInitialLoadRef.current = false
      }, 500)
    }
  }, [dateBounds.min, dateBounds.max, viewStartDate, viewEndDate])

  // Update view dates and percentage base based on visible range
  const updateVisibleRangeState = useCallback(() => {
    if (!chartRef.current) return
    if (isInitialLoadRef.current) return
    if (isUserTypingDateRef.current) return

    const visibleRange = chartRef.current.timeScale().getVisibleRange()
    if (!visibleRange) return

    const fromTime = typeof visibleRange.from === 'string'
      ? visibleRange.from
      : new Date((visibleRange.from as number) * 1000).toISOString().split('T')[0]
    const toTime = typeof visibleRange.to === 'string'
      ? visibleRange.to
      : new Date((visibleRange.to as number) * 1000).toISOString().split('T')[0]

    isChartInteractionRef.current = true
    setViewStartDate(fromTime)
    setViewEndDate(toTime)

    // Update percentage base using first strategy's timeseries
    if (displayMode === 'percentage' && primaryData?.timeseries) {
      const timeseries = primaryData.timeseries
      const firstVisibleIndex = timeseries.findIndex(point => point.date >= fromTime)
      if (firstVisibleIndex !== -1 && firstVisibleIndex !== percentageBaseIndex) {
        setPercentageBaseIndex(firstVisibleIndex)
      }
    }
  }, [primaryData?.timeseries, displayMode, percentageBaseIndex])

  useEffect(() => {
    recalcFnRef.current = updateVisibleRangeState
  }, [updateVisibleRangeState])

  const handleVisibleRangeChange = useCallback(() => {
    if (recalcDebounceRef.current) {
      clearTimeout(recalcDebounceRef.current)
    }
    recalcDebounceRef.current = setTimeout(() => {
      if (recalcFnRef.current) {
        recalcFnRef.current()
      }
    }, 150)
  }, [])

  useEffect(() => {
    visibleRangeHandlerRef.current = handleVisibleRangeChange
  }, [handleVisibleRangeChange])

  const applyDateRangeToChart = useCallback(() => {
    if (!chartRef.current) return
    if (isChartInteractionRef.current) {
      isChartInteractionRef.current = false
      return
    }

    if (viewStartDate && viewEndDate) {
      chartRef.current.timeScale().setVisibleRange({
        from: viewStartDate as Time,
        to: viewEndDate as Time,
      })
    } else {
      chartRef.current.timeScale().fitContent()
    }
  }, [viewStartDate, viewEndDate])

  const handleResetZoom = useCallback(() => {
    setFilterStartDate('')
    setFilterEndDate('')
    setViewStartDate(dateBounds.min)
    setViewEndDate(dateBounds.max)
    setPercentageBaseIndex(0)
    isInitialLoadRef.current = true
    if (chartRef.current) {
      chartRef.current.timeScale().fitContent()
    }
    setTimeout(() => {
      isInitialLoadRef.current = false
    }, 500)
  }, [dateBounds.min, dateBounds.max])

  // Initialize chart
  useEffect(() => {
    if (!chartContainerRef.current) return
    if (chartRef.current) return

    const chartHeight = isMobile ? 250 : 350
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
    })

    // Subscribe to visible range changes
    const rangeChangeWrapper = () => {
      if (visibleRangeHandlerRef.current) {
        visibleRangeHandlerRef.current()
      }
    }
    chartRef.current.timeScale().subscribeVisibleTimeRangeChange(rangeChangeWrapper)

    // Resize observer
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
      if (recalcDebounceRef.current) {
        clearTimeout(recalcDebounceRef.current)
        recalcDebounceRef.current = null
      }
      if (chartRef.current) {
        chartRef.current.timeScale().unsubscribeVisibleTimeRangeChange(rangeChangeWrapper)
        chartRef.current.remove()
        chartRef.current = null
        strategySeriesRefs.current.clear()
        baselineSeriesRef.current = null
      }
    }
  }, [isMobile])

  // Update chart data when strategies or data changes
  useEffect(() => {
    if (!chartRef.current || !chartReady) return

    // Get price formatter based on display mode
    const priceFormatter = displayMode === 'absolute'
      ? (price: number) => `$${price.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
      : (price: number) => {
          const sign = price >= 0 ? '+' : ''
          return `${sign}${price.toFixed(2)}%`
        }

    chartRef.current.applyOptions({
      localization: { priceFormatter },
    })

    // Track which series we need
    const neededStrategyIds = new Set(selectedStrategies)

    // Remove series for strategies that are no longer selected
    for (const [strategyId, series] of strategySeriesRefs.current.entries()) {
      if (!neededStrategyIds.has(strategyId)) {
        chartRef.current.removeSeries(series)
        strategySeriesRefs.current.delete(strategyId)
      }
    }

    // Add or update series for each selected strategy
    let baselineAdded = false

    for (let i = 0; i < selectedStrategies.length; i++) {
      const strategyId = selectedStrategies[i]
      const data = multiStrategyData[strategyId]
      if (!data?.timeseries || data.timeseries.length === 0) continue

      const style = getColorForStrategy(strategyId)
      const timeseries = data.timeseries

      // Calculate base values for percentage mode
      const baseIndex = Math.min(percentageBaseIndex, timeseries.length - 1)
      const basePortfolio = timeseries[baseIndex]?.portfolio ?? 1
      const baseBaseline = timeseries[baseIndex]?.baseline ?? 1

      // Get or create series for this strategy
      let series = strategySeriesRefs.current.get(strategyId)
      if (!series) {
        series = chartRef.current.addLineSeries({
          color: style.color,
          lineWidth: 2,
          lineStyle: style.lineStyle,
        })
        strategySeriesRefs.current.set(strategyId, series)
      } else {
        // Update existing series styling
        series.applyOptions({
          color: style.color,
          lineStyle: style.lineStyle,
        })
      }

      series.applyOptions({
        priceFormat: { type: 'custom', formatter: priceFormatter },
      })

      // Prepare data based on display mode
      if (displayMode === 'absolute') {
        const portfolioData: LineData[] = timeseries
          .filter(point => point.portfolio != null)
          .map(point => ({
            time: point.date as string,
            value: point.portfolio!,
          }))
        series.setData(portfolioData)
      } else {
        const portfolioData: LineData[] = timeseries
          .filter(point => point.portfolio != null)
          .map(point => ({
            time: point.date as string,
            value: basePortfolio > 0 ? (point.portfolio! / basePortfolio - 1) * 100 : 0,
          }))
        series.setData(portfolioData)
      }

      // Add baseline series only once (from first strategy with data)
      if (!baselineAdded && timeseries.some(p => p.baseline != null)) {
        if (!baselineSeriesRef.current) {
          baselineSeriesRef.current = chartRef.current.addLineSeries({
            color: baselineStyle.color,
            lineWidth: 2,
            lineStyle: baselineStyle.lineStyle,
          })
        }

        baselineSeriesRef.current.applyOptions({
          priceFormat: { type: 'custom', formatter: priceFormatter },
        })

        if (displayMode === 'absolute') {
          const baselineData: LineData[] = timeseries
            .filter(point => point.baseline != null)
            .map(point => ({
              time: point.date as string,
              value: point.baseline!,
            }))
          baselineSeriesRef.current.setData(baselineData)
        } else {
          const baselineData: LineData[] = timeseries
            .filter(point => point.baseline != null)
            .map(point => ({
              time: point.date as string,
              value: baseBaseline > 0 ? (point.baseline! / baseBaseline - 1) * 100 : 0,
            }))
          baselineSeriesRef.current.setData(baselineData)
        }
        baselineAdded = true
      }
    }

    // Remove baseline if no strategies have baseline data
    if (!baselineAdded && baselineSeriesRef.current) {
      chartRef.current.removeSeries(baselineSeriesRef.current)
      baselineSeriesRef.current = null
    }

    // Fit content if no view range is set
    if (!viewStartDate && !viewEndDate) {
      chartRef.current.timeScale().fitContent()
    }
  }, [multiStrategyData, selectedStrategies, displayMode, chartReady, viewStartDate, viewEndDate, percentageBaseIndex, getColorForStrategy, baselineStyle])

  // Apply date range when dates change from inputs
  useEffect(() => {
    if (chartReady) {
      applyDateRangeToChart()
    }
  }, [chartReady, applyDateRangeToChart])

  // Prepare strategy styles map for comparison components
  const strategyStyles = useMemo(() => {
    const styles: Record<string, StrategyStyle> = {}
    for (const strategyId of selectedStrategies) {
      styles[strategyId] = getColorForStrategy(strategyId)
    }
    return styles
  }, [selectedStrategies, getColorForStrategy])

  // Show loading or empty state
  const showLoading = isMultiLoading
  const hasAnyData = selectedStrategies.some((id: string) =>
    multiStrategyData[id]?.timeseries && multiStrategyData[id].timeseries.length > 0
  )
  const showEmpty = !isMultiLoading && !hasAnyData && selectedStrategies.length > 0

  if (selectedStrategies.length === 0) {
    return (
      <div className="space-y-4 sm:space-y-6">
        <div className="flex flex-col gap-3">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div>
              <ResponsiveText variant="h1" as="h2" className="text-white flex items-center gap-2">
                <TrendingUp className="w-6 h-6 text-blue-400" />
                Backtest Results
              </ResponsiveText>
            </div>
          </div>
          <StrategyMultiSelector compact={isMobile} />
        </div>

        <div className="flex flex-col items-center justify-center h-64 text-center">
          <BarChart3 className="w-16 h-16 text-gray-500 mb-4" />
          <ResponsiveText variant="h2" as="h2" className="text-white mb-2">
            Select Strategies to Compare
          </ResponsiveText>
          <ResponsiveText variant="body" className="text-gray-400 max-w-md">
            Choose up to 3 strategies from the dropdown above to view and compare their backtest performance.
          </ResponsiveText>
        </div>
      </div>
    )
  }

  if (showEmpty) {
    return (
      <div className="space-y-4 sm:space-y-6">
        <div className="flex flex-col gap-3">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div>
              <ResponsiveText variant="h1" as="h2" className="text-white flex items-center gap-2">
                <TrendingUp className="w-6 h-6 text-blue-400" />
                Backtest Results
              </ResponsiveText>
            </div>
          </div>
          <StrategyMultiSelector compact={isMobile} />
        </div>

        <div className="flex flex-col items-center justify-center h-64 text-center">
          <BarChart3 className="w-16 h-16 text-gray-500 mb-4" />
          <ResponsiveText variant="h2" as="h2" className="text-white mb-2">
            No Backtest Data Available
          </ResponsiveText>
          <ResponsiveText variant="body" className="text-gray-400 max-w-md">
            Run a backtest with dashboard export enabled to view results here.
            The dashboard CSV should be placed in config/backtest/ directory.
          </ResponsiveText>
        </div>
      </div>
    )
  }

  // Get primary summary for header info (when not in comparison mode)
  const primarySummary = primaryData?.summary
  const primaryPeriodMetrics = primaryData?.period_metrics

  return (
    <div className="space-y-4 sm:space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-3">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <ResponsiveText variant="h1" as="h2" className="text-white flex items-center gap-2">
              <TrendingUp className="w-6 h-6 text-blue-400" />
              {isComparisonMode ? 'Strategy Comparison' : 'Backtest Results'}
            </ResponsiveText>
            {!isComparisonMode && primarySummary?.strategy_name && (
              <ResponsiveText variant="small" className="text-gray-400 mt-1">
                Strategy: {primarySummary.strategy_name}
              </ResponsiveText>
            )}
            {isComparisonMode && (
              <ResponsiveText variant="small" className="text-gray-400 mt-1">
                Comparing {selectedStrategies.length} strategies
              </ResponsiveText>
            )}
          </div>
        </div>

        {/* Strategy Multi-Selector */}
        <StrategyMultiSelector compact={isMobile} />
      </div>

      {/* All-Time Metrics - Single Strategy View */}
      {!isComparisonMode && primarySummary && (
        <ResponsiveCard padding="md">
          <ResponsiveText variant="h3" as="h3" className="text-white mb-3">
            All-Time Performance ({primarySummary.start_date} to {primarySummary.end_date})
          </ResponsiveText>
          <ResponsiveGrid columns={{ default: 2, md: 3, lg: 6 }} gap="md">
            <MetricCard
              label="Initial Capital"
              value={primarySummary.initial_capital ?? 0}
              format="currency"
            />
            <MetricCard
              label="Total Return"
              value={primarySummary.total_return ?? 0}
              format="percent"
            />
            <MetricCard
              label="CAGR"
              value={primarySummary.annualized_return ?? 0}
              format="percent"
            />
            <MetricCard
              label="Sharpe Ratio"
              value={primarySummary.sharpe_ratio ?? 0}
              format="number"
            />
            <MetricCard
              label="Max Drawdown"
              value={primarySummary.max_drawdown ?? 0}
              format="percent"
            />
            <MetricCard
              label="Alpha vs QQQ"
              value={primarySummary.alpha ?? 0}
              format="percent"
            />
          </ResponsiveGrid>
        </ResponsiveCard>
      )}

      {/* All-Time Metrics - Comparison View */}
      {isComparisonMode && (
        <ResponsiveCard padding="md">
          <ResponsiveText variant="h3" as="h3" className="text-white mb-3">
            All-Time Performance Comparison
          </ResponsiveText>

          {isMobile ? (
            // Mobile card view for comparison
            <div className="space-y-3">
              {selectedStrategies.map((strategyId: string, idx: number) => {
                const data = multiStrategyData[strategyId]
                const summary = data?.summary
                if (!summary) return null

                return (
                  <MobileComparisonCard
                    key={strategyId}
                    strategyName={summary.strategy_name || strategyId}
                    style={strategyStyles[strategyId]}
                    metrics={{
                      totalReturn: summary.total_return,
                      cagr: summary.annualized_return,
                      sharpe: summary.sharpe_ratio,
                      maxDrawdown: summary.max_drawdown,
                      alpha: summary.alpha,
                    }}
                    rank={idx + 1}
                  />
                )
              })}
              {/* Baseline card */}
              <div className="bg-slate-700/30 rounded-lg p-4 border border-dashed border-slate-600">
                <div className="flex items-center gap-2 mb-3">
                  <span
                    className="w-4 h-4 rounded-full"
                    style={{ backgroundColor: BASELINE_STYLE.color }}
                  />
                  <span className="font-medium text-gray-400">Baseline (QQQ)</span>
                </div>
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <span className="text-gray-400 block">Total Return</span>
                    <span className={(primarySummary?.baseline_total_return ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}>
                      {formatPercent(primarySummary?.baseline_total_return)}
                    </span>
                  </div>
                  <div>
                    <span className="text-gray-400 block">CAGR</span>
                    <span className={(primarySummary?.baseline_cagr ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}>
                      {formatPercent(primarySummary?.baseline_cagr)}
                    </span>
                  </div>
                  <div>
                    <span className="text-gray-400 block">Sharpe</span>
                    <span className="text-gray-200">{formatNumber(primarySummary?.baseline_sharpe_ratio)}</span>
                  </div>
                  <div>
                    <span className="text-gray-400 block">Max DD</span>
                    <span className="text-red-400">{formatPercent(primarySummary?.baseline_max_drawdown)}</span>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            // Desktop table view for comparison
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead className="text-sm text-gray-400 border-b border-slate-700">
                  <tr>
                    <th className="pb-3">Metric</th>
                    {selectedStrategies.map((strategyId: string) => {
                      const data = multiStrategyData[strategyId]
                      const style = strategyStyles[strategyId]
                      return (
                        <th key={strategyId} className="pb-3">
                          <div className="flex items-center gap-2">
                            <span
                              className="w-3 h-3 rounded-full"
                              style={{ backgroundColor: style?.color || '#6b7280' }}
                            />
                            {data?.summary?.strategy_name || strategyId}
                          </div>
                        </th>
                      )
                    })}
                    <th className="pb-3">
                      <div className="flex items-center gap-2">
                        <span
                          className="w-3 h-3 rounded-full"
                          style={{ backgroundColor: BASELINE_STYLE.color }}
                        />
                        QQQ (Baseline)
                      </div>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <ComparisonRow
                    label="Total Return"
                    values={Object.fromEntries(
                      selectedStrategies.map((id: string) => [id, multiStrategyData[id]?.summary?.total_return])
                    )}
                    strategyStyles={strategyStyles}
                    format="percent"
                    higherIsBetter={true}
                    baselineValue={primarySummary?.baseline_total_return}
                    strategyOrder={selectedStrategies}
                  />
                  <ComparisonRow
                    label="CAGR"
                    values={Object.fromEntries(
                      selectedStrategies.map((id: string) => [id, multiStrategyData[id]?.summary?.annualized_return])
                    )}
                    strategyStyles={strategyStyles}
                    format="percent"
                    higherIsBetter={true}
                    baselineValue={primarySummary?.baseline_cagr}
                    strategyOrder={selectedStrategies}
                  />
                  <ComparisonRow
                    label="Sharpe Ratio"
                    values={Object.fromEntries(
                      selectedStrategies.map((id: string) => [id, multiStrategyData[id]?.summary?.sharpe_ratio])
                    )}
                    strategyStyles={strategyStyles}
                    format="number"
                    higherIsBetter={true}
                    baselineValue={primarySummary?.baseline_sharpe_ratio}
                    strategyOrder={selectedStrategies}
                  />
                  <ComparisonRow
                    label="Max Drawdown"
                    values={Object.fromEntries(
                      selectedStrategies.map((id: string) => [id, multiStrategyData[id]?.summary?.max_drawdown])
                    )}
                    strategyStyles={strategyStyles}
                    format="percent"
                    higherIsBetter={false}
                    baselineValue={primarySummary?.baseline_max_drawdown}
                    strategyOrder={selectedStrategies}
                  />
                  <ComparisonRow
                    label="Alpha vs QQQ"
                    values={Object.fromEntries(
                      selectedStrategies.map((id: string) => [id, multiStrategyData[id]?.summary?.alpha])
                    )}
                    strategyStyles={strategyStyles}
                    format="percent"
                    higherIsBetter={true}
                    strategyOrder={selectedStrategies}
                  />
                </tbody>
              </table>
            </div>
          )}
        </ResponsiveCard>
      )}

      {/* Date Range Selector */}
      <ResponsiveCard padding="md">
        <div className="flex flex-col sm:flex-row sm:items-center gap-4">
          <div className="flex items-center gap-2">
            <Calendar className="w-5 h-5 text-gray-400" />
            <ResponsiveText variant="h3" as="h3" className="text-white">
              Date Range
            </ResponsiveText>
          </div>

          <div className="flex flex-col xs:flex-row gap-2 sm:gap-4 flex-1">
            <div className="flex items-center gap-2">
              <label className="text-sm text-gray-400 whitespace-nowrap">From:</label>
              <input
                type="date"
                value={viewStartDate}
                min={dateBounds.min}
                max={dateBounds.max}
                onChange={(e) => {
                  isUserTypingDateRef.current = true
                  setViewStartDate(e.target.value)
                  setFilterStartDate(e.target.value)
                  setTimeout(() => { isUserTypingDateRef.current = false }, 500)
                }}
                className="px-3 py-2 bg-slate-700 rounded-lg border border-slate-600 min-h-[44px] text-sm"
              />
            </div>
            <div className="flex items-center gap-2">
              <label className="text-sm text-gray-400 whitespace-nowrap">To:</label>
              <input
                type="date"
                value={viewEndDate}
                min={viewStartDate || dateBounds.min}
                max={dateBounds.max}
                onChange={(e) => {
                  isUserTypingDateRef.current = true
                  setViewEndDate(e.target.value)
                  setFilterEndDate(e.target.value)
                  setTimeout(() => { isUserTypingDateRef.current = false }, 500)
                }}
                className="px-3 py-2 bg-slate-700 rounded-lg border border-slate-600 min-h-[44px] text-sm"
              />
            </div>
            <button
              onClick={handleResetZoom}
              className="px-4 py-2 bg-slate-600 hover:bg-slate-500 rounded-lg text-sm min-h-[44px] transition-colors"
            >
              Reset
            </button>
          </div>
        </div>
      </ResponsiveCard>

      {/* Period Metrics - Single Strategy */}
      {!isComparisonMode && primaryPeriodMetrics && (filterStartDate || filterEndDate) && (
        <ResponsiveCard padding="md">
          <ResponsiveText variant="h3" as="h3" className="text-white mb-3">
            Selected Period ({primaryPeriodMetrics.start_date} to {primaryPeriodMetrics.end_date})
          </ResponsiveText>
          <ResponsiveGrid columns={{ default: 2, md: 3, lg: 5 }} gap="md">
            <MetricCard
              label="Period Return"
              value={primaryPeriodMetrics.period_return ?? 0}
              format="percent"
            />
            <MetricCard
              label="Annualized"
              value={primaryPeriodMetrics.annualized_return ?? 0}
              format="percent"
            />
            <MetricCard
              label="Baseline Return"
              value={primaryPeriodMetrics.baseline_return ?? 0}
              format="percent"
            />
            <MetricCard
              label="Baseline CAGR"
              value={primaryPeriodMetrics.baseline_annualized ?? 0}
              format="percent"
            />
            <MetricCard
              label="Alpha"
              value={primaryPeriodMetrics.alpha ?? 0}
              format="percent"
            />
          </ResponsiveGrid>
          <ResponsiveText variant="small" className="text-gray-500 mt-2">
            {primaryPeriodMetrics.days} calendar days
          </ResponsiveText>
        </ResponsiveCard>
      )}

      {/* Period Metrics - Comparison View */}
      {isComparisonMode && (filterStartDate || filterEndDate) && selectedStrategies.some(
        (id: string) => multiStrategyData[id]?.period_metrics
      ) && (
        <ResponsiveCard padding="md">
          <ResponsiveText variant="h3" as="h3" className="text-white mb-3">
            Selected Period Comparison
            {primaryPeriodMetrics && ` (${primaryPeriodMetrics.start_date} to ${primaryPeriodMetrics.end_date})`}
          </ResponsiveText>

          {isMobile ? (
            // Mobile card view for period comparison
            <div className="space-y-3">
              {selectedStrategies.map((strategyId: string) => {
                const data = multiStrategyData[strategyId]
                const periodMetrics = data?.period_metrics
                if (!periodMetrics) return null

                return (
                  <div key={strategyId} className="bg-slate-700/50 rounded-lg p-4">
                    <div className="flex items-center gap-2 mb-3">
                      <span
                        className="w-4 h-4 rounded-full"
                        style={{ backgroundColor: strategyStyles[strategyId]?.color || '#6b7280' }}
                      />
                      <span className="font-medium text-white">{data?.summary?.strategy_name || strategyId}</span>
                    </div>
                    <div className="grid grid-cols-2 gap-3 text-sm">
                      <div>
                        <span className="text-gray-400 block">Period Return</span>
                        <span className={(periodMetrics.period_return ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}>
                          {formatPercent(periodMetrics.period_return)}
                        </span>
                      </div>
                      <div>
                        <span className="text-gray-400 block">Annualized</span>
                        <span className={(periodMetrics.annualized_return ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}>
                          {formatPercent(periodMetrics.annualized_return)}
                        </span>
                      </div>
                      <div>
                        <span className="text-gray-400 block">Alpha</span>
                        <span className={(periodMetrics.alpha ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}>
                          {formatPercent(periodMetrics.alpha)}
                        </span>
                      </div>
                      <div>
                        <span className="text-gray-400 block">Days</span>
                        <span className="text-gray-200">{periodMetrics.days}</span>
                      </div>
                    </div>
                  </div>
                )
              })}
              {/* Baseline info */}
              {primaryPeriodMetrics && (
                <div className="bg-slate-700/30 rounded-lg p-4 border border-dashed border-slate-600">
                  <div className="flex items-center gap-2 mb-3">
                    <span
                      className="w-4 h-4 rounded-full"
                      style={{ backgroundColor: BASELINE_STYLE.color }}
                    />
                    <span className="font-medium text-gray-400">Baseline (QQQ)</span>
                  </div>
                  <div className="grid grid-cols-2 gap-3 text-sm">
                    <div>
                      <span className="text-gray-400 block">Period Return</span>
                      <span className={(primaryPeriodMetrics.baseline_return ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}>
                        {formatPercent(primaryPeriodMetrics.baseline_return)}
                      </span>
                    </div>
                    <div>
                      <span className="text-gray-400 block">Annualized</span>
                      <span className={(primaryPeriodMetrics.baseline_annualized ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}>
                        {formatPercent(primaryPeriodMetrics.baseline_annualized)}
                      </span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          ) : (
            // Desktop table view for period comparison
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead className="text-sm text-gray-400 border-b border-slate-700">
                  <tr>
                    <th className="pb-3">Metric</th>
                    {selectedStrategies.map((strategyId: string) => {
                      const data = multiStrategyData[strategyId]
                      const style = strategyStyles[strategyId]
                      return (
                        <th key={strategyId} className="pb-3">
                          <div className="flex items-center gap-2">
                            <span
                              className="w-3 h-3 rounded-full"
                              style={{ backgroundColor: style?.color || '#6b7280' }}
                            />
                            {data?.summary?.strategy_name || strategyId}
                          </div>
                        </th>
                      )
                    })}
                    <th className="pb-3">
                      <div className="flex items-center gap-2">
                        <span
                          className="w-3 h-3 rounded-full"
                          style={{ backgroundColor: BASELINE_STYLE.color }}
                        />
                        QQQ (Baseline)
                      </div>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <ComparisonRow
                    label="Period Return"
                    values={Object.fromEntries(
                      selectedStrategies.map((id: string) => [id, multiStrategyData[id]?.period_metrics?.period_return])
                    )}
                    strategyStyles={strategyStyles}
                    format="percent"
                    higherIsBetter={true}
                    baselineValue={primaryPeriodMetrics?.baseline_return}
                    strategyOrder={selectedStrategies}
                  />
                  <ComparisonRow
                    label="Annualized"
                    values={Object.fromEntries(
                      selectedStrategies.map((id: string) => [id, multiStrategyData[id]?.period_metrics?.annualized_return])
                    )}
                    strategyStyles={strategyStyles}
                    format="percent"
                    higherIsBetter={true}
                    baselineValue={primaryPeriodMetrics?.baseline_annualized}
                    strategyOrder={selectedStrategies}
                  />
                  <ComparisonRow
                    label="Alpha vs QQQ"
                    values={Object.fromEntries(
                      selectedStrategies.map((id: string) => [id, multiStrategyData[id]?.period_metrics?.alpha])
                    )}
                    strategyStyles={strategyStyles}
                    format="percent"
                    higherIsBetter={true}
                    strategyOrder={selectedStrategies}
                  />
                </tbody>
              </table>
              {primaryPeriodMetrics?.days && (
                <ResponsiveText variant="small" className="text-gray-500 mt-2">
                  {primaryPeriodMetrics.days} calendar days
                </ResponsiveText>
              )}
            </div>
          )}
        </ResponsiveCard>
      )}

      {/* Equity Curve Chart */}
      <ResponsiveCard padding="md">
        {/* Display mode toggle */}
        <div className="flex justify-end mb-4">
          <div className="flex items-center gap-2">
            <button
              onClick={() => setDisplayMode('percentage')}
              className={`px-3 py-2 rounded-lg text-sm min-h-[44px] transition-colors ${
                displayMode === 'percentage'
                  ? 'bg-blue-600 text-white'
                  : 'bg-slate-700 text-gray-300 hover:bg-slate-600'
              }`}
            >
              % Return
            </button>
            <button
              onClick={() => setDisplayMode('absolute')}
              className={`px-3 py-2 rounded-lg text-sm min-h-[44px] transition-colors ${
                displayMode === 'absolute'
                  ? 'bg-blue-600 text-white'
                  : 'bg-slate-700 text-gray-300 hover:bg-slate-600'
              }`}
            >
              $ Value
            </button>
          </div>
        </div>
        <div className="flex flex-col sm:flex-row sm:items-center justify-between mb-4 gap-2">
          <div>
            <ResponsiveText variant="h2" as="h3" className="text-white">
              {displayMode === 'absolute' ? 'Equity Curves' : 'Performance (% Return)'}
            </ResponsiveText>
            <ResponsiveText variant="small" className="text-gray-400">
              {displayMode === 'absolute'
                ? 'Absolute portfolio value over time'
                : 'Percentage return from backtest start'}
            </ResponsiveText>
          </div>
          {/* Chart Legend */}
          <div className="flex flex-wrap items-center gap-4 text-xs sm:text-sm">
            {selectedStrategies.map((strategyId: string) => {
              const data = multiStrategyData[strategyId]
              const style = strategyStyles[strategyId]
              return (
                <div key={strategyId} className="flex items-center gap-2">
                  <div
                    className="w-4 h-0.5"
                    style={{
                      backgroundColor: style?.color || '#6b7280',
                      borderStyle: style?.lineStyle === LineStyle.Dashed ? 'dashed' :
                                   style?.lineStyle === LineStyle.Dotted ? 'dotted' :
                                   style?.lineStyle === LineStyle.LargeDashed ? 'dashed' : 'solid',
                      borderWidth: style?.lineStyle !== LineStyle.Solid ? '2px 0 0 0' : '0',
                      borderColor: style?.color || '#6b7280',
                    }}
                  />
                  <span className="text-gray-400">{data?.summary?.strategy_name || strategyId}</span>
                </div>
              )
            })}
            <div className="flex items-center gap-2">
              <div
                className="w-4 h-0.5"
                style={{
                  borderTop: `2px dashed ${BASELINE_STYLE.color}`,
                }}
              />
              <span className="text-gray-400">QQQ</span>
            </div>
          </div>
        </div>
        <div className="relative" style={{ minHeight: isMobile ? 250 : 350 }}>
          <div ref={chartContainerRef} className="w-full" />
          {showLoading && (
            <div className="absolute inset-0 flex items-center justify-center bg-slate-800/50">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-400"></div>
            </div>
          )}
        </div>
        <ResponsiveText variant="small" className="text-gray-500 mt-2">
          Drag to pan, scroll to zoom. Date inputs sync with chart view.
        </ResponsiveText>
      </ResponsiveCard>

      {/* Regime Performance Table */}
      {regimeData?.regimes && regimeData.regimes.length > 0 && (
        <ResponsiveCard padding="md">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
            <ResponsiveText variant="h2" as="h3" className="text-white">
              Performance by Regime
            </ResponsiveText>
            {isComparisonMode && (
              <div className="flex items-center gap-2">
                <label className="text-sm text-gray-400">Strategy:</label>
                <select
                  value={regimeTableStrategy}
                  onChange={(e) => setRegimeTableStrategy(e.target.value)}
                  className="px-3 py-2 bg-slate-700 rounded-lg border border-slate-600 text-sm min-h-[44px]"
                >
                  {selectedStrategies.map((strategyId: string) => {
                    const data = multiStrategyData[strategyId]
                    return (
                      <option key={strategyId} value={strategyId}>
                        {data?.summary?.strategy_name || strategyId}
                      </option>
                    )
                  })}
                </select>
              </div>
            )}
          </div>

          {isMobile ? (
            // Mobile Card View
            <div className="space-y-3">
              {regimeData.regimes.map((regime, idx) => (
                <div key={idx} className="bg-slate-700/50 rounded-lg p-4">
                  <div className="flex items-center justify-between mb-3">
                    <span className="px-2 py-1 bg-slate-600 rounded font-mono text-sm">
                      {regime.regime}
                    </span>
                    <span className="text-gray-400 text-sm">
                      {regime.days} days ({regime.pct_of_time.toFixed(1)}%)
                    </span>
                  </div>
                  <div className="grid grid-cols-2 gap-3 text-sm">
                    <div>
                      <span className="text-gray-400 block">Trend</span>
                      <span className={
                        regime.trend?.includes('Bull') ? 'text-green-400' :
                        regime.trend?.includes('Bear') ? 'text-red-400' : 'text-yellow-400'
                      }>
                        {regime.trend || '-'}
                      </span>
                    </div>
                    <div>
                      <span className="text-gray-400 block">Volatility</span>
                      <span className={
                        regime.vol === 'Low' ? 'text-green-400' :
                        regime.vol === 'High' ? 'text-red-400' : 'text-yellow-400'
                      }>
                        {regime.vol || '-'}
                      </span>
                    </div>
                    <div>
                      <span className="text-gray-400 block">Return</span>
                      <span className={regime.total_return >= 0 ? 'text-green-400' : 'text-red-400'}>
                        {formatPercent(regime.total_return)}
                      </span>
                    </div>
                    <div>
                      <span className="text-gray-400 block">Annualized</span>
                      <span className={
                        (regime.annualized_return ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'
                      }>
                        {formatPercent(regime.annualized_return)}
                      </span>
                    </div>
                    <div>
                      <span className="text-gray-400 block">Baseline Ann.</span>
                      <span className={
                        (regime.baseline_annualized ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'
                      }>
                        {formatPercent(regime.baseline_annualized)}
                      </span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            // Desktop Table View
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead className="text-sm text-gray-400 border-b border-slate-700">
                  <tr>
                    <th className="pb-3">Regime</th>
                    {!isTablet && <th className="pb-3">Trend</th>}
                    {!isTablet && <th className="pb-3">Volatility</th>}
                    <th className="pb-3">Return</th>
                    <th className="pb-3">Annualized</th>
                    <th className="pb-3">Baseline Ann.</th>
                    <th className="pb-3">Days</th>
                    <th className="pb-3">% of Time</th>
                  </tr>
                </thead>
                <tbody>
                  {regimeData.regimes.map((regime, idx) => (
                    <tr key={idx} className="border-b border-slate-700/50">
                      <td className="py-3">
                        <span className="px-2 py-1 bg-slate-700 rounded font-mono text-sm">
                          {regime.regime}
                        </span>
                      </td>
                      {!isTablet && (
                        <td className={`py-3 ${
                          regime.trend?.includes('Bull') ? 'text-green-400' :
                          regime.trend?.includes('Bear') ? 'text-red-400' : 'text-yellow-400'
                        }`}>
                          {regime.trend || '-'}
                        </td>
                      )}
                      {!isTablet && (
                        <td className={`py-3 ${
                          regime.vol === 'Low' ? 'text-green-400' :
                          regime.vol === 'High' ? 'text-red-400' : 'text-yellow-400'
                        }`}>
                          {regime.vol || '-'}
                        </td>
                      )}
                      <td className={`py-3 ${
                        regime.total_return >= 0 ? 'text-green-400' : 'text-red-400'
                      }`}>
                        {formatPercent(regime.total_return)}
                      </td>
                      <td className={`py-3 ${
                        (regime.annualized_return ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'
                      }`}>
                        {formatPercent(regime.annualized_return)}
                      </td>
                      <td className={`py-3 ${
                        (regime.baseline_annualized ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'
                      }`}>
                        {formatPercent(regime.baseline_annualized)}
                      </td>
                      <td className="py-3 text-gray-300">{regime.days}</td>
                      <td className="py-3 text-gray-300">{regime.pct_of_time.toFixed(1)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </ResponsiveCard>
      )}

      {/* Strategy Config Pane (Admin Only) */}
      {isAdmin && configData?.config && (
        <ResponsiveCard padding="md">
          <button
            onClick={() => setShowConfigPane(!showConfigPane)}
            className="flex items-center justify-between w-full text-left"
          >
            <div className="flex items-center gap-2">
              <Settings className="w-5 h-5 text-gray-400" />
              <ResponsiveText variant="h2" as="h3" className="text-white">
                Strategy Configuration
              </ResponsiveText>
            </div>
            {showConfigPane ? (
              <ChevronUp className="w-5 h-5 text-gray-400" />
            ) : (
              <ChevronDown className="w-5 h-5 text-gray-400" />
            )}
          </button>

          {showConfigPane && (
            <div className="mt-4">
              <ResponsiveText variant="small" className="text-gray-500 mb-3">
                Source: {configData.file_path}
              </ResponsiveText>
              <div className="bg-slate-900 rounded-lg p-4 overflow-x-auto">
                <pre className="text-sm text-gray-300 font-mono whitespace-pre-wrap">
                  {JSON.stringify(configData.config, null, 2)}
                </pre>
              </div>
            </div>
          )}
        </ResponsiveCard>
      )}

      {/* Footer info */}
      {hasAnyData && (
        <ResponsiveText variant="small" className="text-gray-500 text-center">
          {isComparisonMode
            ? `Comparing ${selectedStrategies.length} strategies`
            : primaryData && `Showing ${primaryData.filtered_data_points} of ${primaryData.total_data_points} data points`}
          {primarySummary?.baseline_ticker && ` | Baseline: ${primarySummary.baseline_ticker}`}
        </ResponsiveText>
      )}
    </div>
  )
}

export default BacktestV2
