/**
 * BacktestV2 - Responsive Backtest Dashboard Page
 *
 * Displays golden backtest results with interactive visualizations.
 * Features:
 * - All-time and period metrics
 * - Interactive equity curve with zoom/pan
 * - Bidirectional date-chart synchronization
 * - Regime performance breakdown
 * - Admin-only strategy config viewer
 *
 * @version 1.0.0
 * @part Backtest Dashboard UI - Phase 4
 */

import { useQuery } from '@tanstack/react-query'
import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { ChevronDown, ChevronUp, Settings, Calendar, TrendingUp, BarChart3 } from 'lucide-react'
import { backtestApi } from '../../api/client'
import { createChart, IChartApi, ISeriesApi, LineData, TickMarkType, Time } from 'lightweight-charts'
import { ResponsiveCard, ResponsiveText, ResponsiveGrid, MetricCard } from '../../components/ui'
import { useIsMobileOrSmaller, useIsTablet } from '../../hooks/useMediaQuery'
import { useAuth } from '../../contexts/AuthContext'
import { useStrategy } from '../../contexts/StrategyContext'
import StrategySelector from '../../components/StrategySelector'

// Helper functions
function formatPercent(value: number | null | undefined, decimals = 2): string {
  if (value == null) return '-'
  const sign = value >= 0 ? '+' : ''
  return `${sign}${value.toFixed(decimals)}%`
}

function BacktestV2() {
  const isMobile = useIsMobileOrSmaller()
  const isTablet = useIsTablet()
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const { selectedStrategy } = useStrategy()

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
  // so percentages are recalculated relative to that point
  const [percentageBaseIndex, setPercentageBaseIndex] = useState<number>(0)

  // Chart refs
  const chartContainerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const portfolioSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const baselineSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const [chartReady, setChartReady] = useState(false)
  // Ref to hold latest visible range change handler (avoids recreating chart on date changes)
  const visibleRangeHandlerRef = useRef<(() => void) | null>(null)
  // Debounce timer for percentage recalculation
  const recalcDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Ref to hold latest recalculatePercentages function (avoids stale closure in timeout)
  const recalcFnRef = useRef<(() => void) | null>(null)
  // Flag to track if initial load is complete - prevents date sync during chart initialization
  const isInitialLoadRef = useRef(true)

  // Fetch backtest data - only use filter dates (not view dates from chart zoom)
  const { data: backtestData, isLoading: isLoadingData } = useQuery({
    queryKey: ['backtest-data', filterStartDate, filterEndDate, selectedStrategy],
    queryFn: () => backtestApi.getData({
      start_date: filterStartDate || undefined,
      end_date: filterEndDate || undefined,
      strategy_id: selectedStrategy,
    }).then(res => res.data),
  })

  // Fetch regime breakdown - only use filter dates
  const { data: regimeData } = useQuery({
    queryKey: ['backtest-regime', filterStartDate, filterEndDate, selectedStrategy],
    queryFn: () => backtestApi.getRegimeBreakdown({
      start_date: filterStartDate || undefined,
      end_date: filterEndDate || undefined,
      strategy_id: selectedStrategy,
    }).then(res => res.data),
  })

  // Fetch config (admin only)
  const { data: configData } = useQuery({
    queryKey: ['backtest-config', selectedStrategy],
    queryFn: () => backtestApi.getConfig({ strategy_id: selectedStrategy }).then(res => res.data),
    enabled: isAdmin,
  })

  // Get date bounds from summary (full backtest range, not filtered timeseries)
  const dateBounds = useMemo(() => {
    // Use summary dates for full range (allows selecting any date in backtest period)
    if (backtestData?.summary?.start_date && backtestData?.summary?.end_date) {
      return { min: backtestData.summary.start_date, max: backtestData.summary.end_date }
    }
    // Fallback to timeseries if summary not available
    if (!backtestData?.timeseries || backtestData.timeseries.length === 0) {
      return { min: '', max: '' }
    }
    const dates = backtestData.timeseries.map(d => d.date).sort()
    return { min: dates[0], max: dates[dates.length - 1] }
  }, [backtestData?.summary?.start_date, backtestData?.summary?.end_date, backtestData?.timeseries])

  // Initialize view dates to full backtest range when data loads
  // This ensures date inputs show the full range by default, regardless of window size
  useEffect(() => {
    if (dateBounds.min && dateBounds.max && !viewStartDate && !viewEndDate) {
      setViewStartDate(dateBounds.min)
      setViewEndDate(dateBounds.max)
      // Mark initial load as complete after a short delay to allow chart to finish rendering
      // This prevents the visible range callback from overwriting our initial dates
      setTimeout(() => {
        isInitialLoadRef.current = false
      }, 500)
    }
  }, [dateBounds.min, dateBounds.max, viewStartDate, viewEndDate])

  // Update view dates and percentage base based on visible range - called after debounce
  // This syncs the date inputs with the chart's visible range when user pans/zooms
  const updateVisibleRangeState = useCallback(() => {
    if (!chartRef.current || !backtestData?.timeseries) return

    // Don't update during initial load - preserves full date range as default
    if (isInitialLoadRef.current) return

    // Don't update if user is explicitly typing in date inputs
    if (isUserTypingDateRef.current) return

    const visibleRange = chartRef.current.timeScale().getVisibleRange()
    if (!visibleRange) return

    // Convert visible range to date strings
    const fromTime = typeof visibleRange.from === 'string'
      ? visibleRange.from
      : new Date((visibleRange.from as number) * 1000).toISOString().split('T')[0]
    const toTime = typeof visibleRange.to === 'string'
      ? visibleRange.to
      : new Date((visibleRange.to as number) * 1000).toISOString().split('T')[0]

    // Update view dates to sync with chart (this updates the date inputs)
    // Mark as chart interaction to prevent feedback loop
    isChartInteractionRef.current = true
    setViewStartDate(fromTime)
    setViewEndDate(toTime)

    // Update percentage base in percentage mode
    if (displayMode === 'percentage') {
      const timeseries = backtestData.timeseries
      // Find first data point that is >= the visible range start
      const firstVisibleIndex = timeseries.findIndex(point => point.date >= fromTime)
      if (firstVisibleIndex !== -1 && firstVisibleIndex !== percentageBaseIndex) {
        setPercentageBaseIndex(firstVisibleIndex)
      }
    }
  }, [backtestData?.timeseries, displayMode, percentageBaseIndex])

  // Keep recalcFnRef updated with latest function
  useEffect(() => {
    recalcFnRef.current = updateVisibleRangeState
  }, [updateVisibleRangeState])

  // Handle chart range changes - debounced to avoid issues during active panning
  // This syncs date inputs with visible range and recalculates percentages.
  // IMPORTANT: Updates view dates (for display) but NOT filter dates (no API refetch).
  const handleVisibleRangeChange = useCallback(() => {
    // Clear any pending recalculation
    if (recalcDebounceRef.current) {
      clearTimeout(recalcDebounceRef.current)
    }
    // Debounce: wait 150ms after user stops panning/zooming before recalculating
    // Use ref to always get latest function and avoid stale closure
    recalcDebounceRef.current = setTimeout(() => {
      if (recalcFnRef.current) {
        recalcFnRef.current()
      }
    }, 150)
  }, []) // No dependencies - always uses ref for latest function

  // Keep ref updated with latest handler
  useEffect(() => {
    visibleRangeHandlerRef.current = handleVisibleRangeChange
  }, [handleVisibleRangeChange])

  // Apply date range to chart - when view dates change from inputs (not chart interaction)
  const applyDateRangeToChart = useCallback(() => {
    if (!chartRef.current || !backtestData?.timeseries) return
    // Skip if this was triggered by chart interaction (avoids feedback loop)
    if (isChartInteractionRef.current) {
      isChartInteractionRef.current = false
      return
    }

    if (viewStartDate && viewEndDate) {
      // Set visible range to match date inputs
      chartRef.current.timeScale().setVisibleRange({
        from: viewStartDate as Time,
        to: viewEndDate as Time,
      })
    } else {
      // Fit all content
      chartRef.current.timeScale().fitContent()
    }
  }, [viewStartDate, viewEndDate, backtestData?.timeseries])

  // Reset zoom handler - resets filter dates and restores view to full range
  const handleResetZoom = useCallback(() => {
    // Clear filter dates (API will return full data)
    setFilterStartDate('')
    setFilterEndDate('')
    // Restore view dates to full backtest range
    setViewStartDate(dateBounds.min)
    setViewEndDate(dateBounds.max)
    // Reset percentage base to first point
    setPercentageBaseIndex(0)
    // Temporarily block date sync while chart resets to prevent overwriting full range
    isInitialLoadRef.current = true
    if (chartRef.current) {
      chartRef.current.timeScale().fitContent()
    }
    // Re-enable date sync after chart settles
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

    portfolioSeriesRef.current = chartRef.current.addLineSeries({
      color: '#3b82f6',
      lineWidth: 2,
      title: 'Portfolio',
    })

    baselineSeriesRef.current = chartRef.current.addLineSeries({
      color: '#f59e0b',
      lineWidth: 2,
      lineStyle: 2,
      title: 'Baseline (QQQ)',
    })

    // Subscribe to visible range changes for bidirectional sync
    // Use a wrapper that calls the ref to always get the latest handler
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
      // Clear debounce timer
      if (recalcDebounceRef.current) {
        clearTimeout(recalcDebounceRef.current)
        recalcDebounceRef.current = null
      }
      if (chartRef.current) {
        chartRef.current.timeScale().unsubscribeVisibleTimeRangeChange(rangeChangeWrapper)
        chartRef.current.remove()
        chartRef.current = null
        portfolioSeriesRef.current = null
        baselineSeriesRef.current = null
      }
    }
  }, [isMobile]) // Only depend on isMobile for chart sizing, not loading state

  // Update chart data when data, display mode, or percentage base changes
  useEffect(() => {
    if (!chartRef.current || !portfolioSeriesRef.current || !backtestData?.timeseries || backtestData.timeseries.length === 0) return

    const timeseries = backtestData.timeseries
    // Use percentageBaseIndex to determine which point is the "base" (0%) for percentage calculations
    // This enables dynamic rebasing when panning/zooming in percentage mode
    const baseIndex = Math.min(percentageBaseIndex, timeseries.length - 1)
    const basePortfolio = timeseries[baseIndex]?.portfolio ?? 1
    const baseBaseline = timeseries[baseIndex]?.baseline ?? 1

    // Configure price formatter based on display mode
    const priceFormatter = displayMode === 'absolute'
      ? (price: number) => `$${price.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
      : (price: number) => {
          const sign = price >= 0 ? '+' : ''
          return `${sign}${price.toFixed(2)}%`
        }

    chartRef.current.applyOptions({
      localization: { priceFormatter },
    })

    portfolioSeriesRef.current.applyOptions({
      priceFormat: { type: 'custom', formatter: priceFormatter },
    })

    if (baselineSeriesRef.current) {
      baselineSeriesRef.current.applyOptions({
        priceFormat: { type: 'custom', formatter: priceFormatter },
      })
    }

    // Prepare chart data
    if (displayMode === 'absolute') {
      const portfolioData: LineData[] = timeseries
        .filter(point => point.portfolio != null)
        .map(point => ({
          time: point.date as string,
          value: point.portfolio!,
        }))
      portfolioSeriesRef.current.setData(portfolioData)

      if (baselineSeriesRef.current) {
        const baselineData: LineData[] = timeseries
          .filter(point => point.baseline != null)
          .map(point => ({
            time: point.date as string,
            value: point.baseline!,
          }))
        baselineSeriesRef.current.setData(baselineData)
      }
    } else {
      // Percentage mode - calculate returns from base point (first visible point after panning)
      const portfolioData: LineData[] = timeseries
        .filter(point => point.portfolio != null)
        .map(point => ({
          time: point.date as string,
          value: basePortfolio > 0 ? (point.portfolio! / basePortfolio - 1) * 100 : 0,
        }))
      portfolioSeriesRef.current.setData(portfolioData)

      if (baselineSeriesRef.current) {
        const baselineData: LineData[] = timeseries
          .filter(point => point.baseline != null)
          .map(point => ({
            time: point.date as string,
            value: baseBaseline > 0 ? (point.baseline! / baseBaseline - 1) * 100 : 0,
          }))
        baselineSeriesRef.current.setData(baselineData)
      }
    }

    // Fit content if no view range is set
    if (!viewStartDate && !viewEndDate) {
      chartRef.current.timeScale().fitContent()
    }
  }, [backtestData?.timeseries, displayMode, chartReady, viewStartDate, viewEndDate, percentageBaseIndex])

  // Apply date range when dates change from inputs (not from chart zoom)
  useEffect(() => {
    if (chartReady) {
      applyDateRangeToChart()
    }
  }, [chartReady, applyDateRangeToChart])

  // Show loading or empty state, but don't return early - keep chart container in DOM
  const showLoading = isLoadingData
  const showEmpty = !isLoadingData && (!backtestData?.timeseries || backtestData.timeseries.length === 0)

  if (showEmpty) {
    return (
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
    )
  }

  const summary = backtestData?.summary
  const period_metrics = backtestData?.period_metrics

  return (
    <div className="space-y-4 sm:space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-3">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <ResponsiveText variant="h1" as="h2" className="text-white flex items-center gap-2">
              <TrendingUp className="w-6 h-6 text-blue-400" />
              Backtest Results
            </ResponsiveText>
            {summary?.strategy_name && (
              <ResponsiveText variant="small" className="text-gray-400 mt-1">
                Strategy: {summary.strategy_name}
              </ResponsiveText>
            )}
          </div>
        </div>

        {/* Strategy Selector */}
        <StrategySelector showCompare={false} compact={isMobile} />
      </div>

      {/* All-Time Metrics (Row 1) */}
      {summary && (
        <ResponsiveCard padding="md">
          <ResponsiveText variant="h3" as="h3" className="text-white mb-3">
            All-Time Performance ({summary.start_date} to {summary.end_date})
          </ResponsiveText>
          <ResponsiveGrid columns={{ default: 2, md: 3, lg: 6 }} gap="md">
            <MetricCard
              label="Initial Capital"
              value={summary.initial_capital ?? 0}
              format="currency"
            />
            <MetricCard
              label="Total Return"
              value={summary.total_return ?? 0}
              format="percent"
            />
            <MetricCard
              label="CAGR"
              value={summary.annualized_return ?? 0}
              format="percent"
            />
            <MetricCard
              label="Sharpe Ratio"
              value={summary.sharpe_ratio ?? 0}
              format="number"
            />
            <MetricCard
              label="Max Drawdown"
              value={summary.max_drawdown ?? 0}
              format="percent"
            />
            <MetricCard
              label="Alpha vs QQQ"
              value={summary.alpha ?? 0}
              format="percent"
            />
          </ResponsiveGrid>
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
                  // Set flag to prevent chart from overwriting user's explicit input
                  isUserTypingDateRef.current = true
                  setViewStartDate(e.target.value)
                  // Update filter dates on explicit user input (triggers data refetch)
                  setFilterStartDate(e.target.value)
                  // Clear flag after a short delay to allow chart to update
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
                  // Set flag to prevent chart from overwriting user's explicit input
                  isUserTypingDateRef.current = true
                  setViewEndDate(e.target.value)
                  // Update filter dates on explicit user input (triggers data refetch)
                  setFilterEndDate(e.target.value)
                  // Clear flag after a short delay to allow chart to update
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

      {/* Period Metrics (Row 2) - when date range is selected */}
      {period_metrics && (filterStartDate || filterEndDate) && (
        <ResponsiveCard padding="md">
          <ResponsiveText variant="h3" as="h3" className="text-white mb-3">
            Selected Period ({period_metrics.start_date} to {period_metrics.end_date})
          </ResponsiveText>
          <ResponsiveGrid columns={{ default: 2, md: 3, lg: 5 }} gap="md">
            <MetricCard
              label="Period Return"
              value={period_metrics.period_return ?? 0}
              format="percent"
            />
            <MetricCard
              label="Annualized"
              value={period_metrics.annualized_return ?? 0}
              format="percent"
            />
            <MetricCard
              label="Baseline Return"
              value={period_metrics.baseline_return ?? 0}
              format="percent"
            />
            <MetricCard
              label="Baseline CAGR"
              value={period_metrics.baseline_annualized ?? 0}
              format="percent"
            />
            <MetricCard
              label="Alpha"
              value={period_metrics.alpha ?? 0}
              format="percent"
            />
          </ResponsiveGrid>
          <ResponsiveText variant="small" className="text-gray-500 mt-2">
            {period_metrics.days} calendar days
          </ResponsiveText>
        </ResponsiveCard>
      )}

      {/* Equity Curve Chart */}
      <ResponsiveCard padding="md">
        {/* Display mode toggle - positioned above chart */}
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
              {displayMode === 'absolute' ? 'Equity Curve' : 'Performance (% Return)'}
            </ResponsiveText>
            <ResponsiveText variant="small" className="text-gray-400">
              {displayMode === 'absolute'
                ? 'Absolute portfolio value over time'
                : 'Percentage return from backtest start'}
            </ResponsiveText>
          </div>
          <div className="flex items-center gap-4 text-xs sm:text-sm">
            <div className="flex items-center gap-2">
              <div className="w-4 h-0.5 bg-blue-500"></div>
              <span className="text-gray-400">Portfolio</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-4 h-0.5 bg-amber-500" style={{ borderTop: '2px dashed #f59e0b' }}></div>
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
          <ResponsiveText variant="h2" as="h3" className="text-white mb-4">
            Performance by Regime
          </ResponsiveText>

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
      {backtestData && (
        <ResponsiveText variant="small" className="text-gray-500 text-center">
          Showing {backtestData.filtered_data_points} of {backtestData.total_data_points} data points
          {summary?.baseline_ticker && ` | Baseline: ${summary.baseline_ticker}`}
        </ResponsiveText>
      )}
    </div>
  )
}

export default BacktestV2
