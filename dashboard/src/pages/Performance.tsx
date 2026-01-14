import { useQuery } from '@tanstack/react-query'
import { useState, useEffect, useRef, useMemo } from 'react'
import { performanceApi } from '../api/client'
import { createChart, IChartApi, ISeriesApi, LineData, TickMarkType } from 'lightweight-charts'

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
      // Year to date: from Jan 1 of current year
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

/**
 * Calculate period return from cumulative returns at start and end of period.
 * Formula: ((1 + endCum/100) / (1 + startCum/100) - 1) * 100
 * This gives the actual return over the selected period, not all-time.
 */
function calculatePeriodReturn(endCumReturn: number, startCumReturn: number): number {
  const startGrowth = 1 + startCumReturn / 100
  const endGrowth = 1 + endCumReturn / 100
  if (startGrowth === 0) return 0 // Guard against division by zero
  return (endGrowth / startGrowth - 1) * 100
}

/**
 * Calculate annualized return (CAGR) from period return and calendar days.
 * Standard CAGR Formula: ((1 + periodReturn)^(365/calendarDays) - 1) * 100
 */
function calculateAnnualizedReturn(periodReturnPct: number, calendarDays: number): number {
  if (calendarDays <= 0) return 0
  const periodReturn = periodReturnPct / 100 // Convert to decimal
  // Handle negative returns properly
  const base = 1 + periodReturn
  if (base <= 0) return -100 // Total loss scenario
  const annualized = Math.pow(base, 365 / calendarDays) - 1
  return annualized * 100 // Convert back to percentage
}

/**
 * Calculate calendar days between first and last snapshot in history.
 */
function calculateCalendarDays(history: Array<{ timestamp?: string }>): number {
  if (!history || history.length < 2) return history?.length || 0
  const firstDate = history[0].timestamp?.slice(0, 10)
  const lastDate = history[history.length - 1].timestamp?.slice(0, 10)
  if (!firstDate || !lastDate) return 0
  const start = new Date(firstDate)
  const end = new Date(lastDate)
  const diffMs = end.getTime() - start.getTime()
  // Add 1 to include both start and end dates
  return Math.floor(diffMs / (1000 * 60 * 60 * 24)) + 1
}

function Performance() {
  const [mode, setMode] = useState('')
  const [timeRange, setTimeRange] = useState<TimeRange>('90d')
  const [showCustomModal, setShowCustomModal] = useState(false)
  const [customStartDate, setCustomStartDate] = useState('')
  const [customEndDate, setCustomEndDate] = useState('')

  // Compute query params from time range
  const queryParams = useMemo(() => 
    getTimeRangeParams(timeRange, customStartDate, customEndDate),
    [timeRange, customStartDate, customEndDate]
  )

  const chartContainerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const baselineSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)

  const { data: performance, isLoading } = useQuery({
    queryKey: ['performance', mode, timeRange, queryParams],
    queryFn: () => performanceApi.getPerformance({
      mode: mode || undefined,
      days: queryParams.days,
      start_date: queryParams.start_date,
    }).then(res => res.data),
  })

  const { data: equityCurve } = useQuery({
    queryKey: ['equityCurve', mode, timeRange, queryParams],
    queryFn: () => performanceApi.getEquityCurve({
      mode: mode || undefined,
      days: queryParams.days,
      start_date: queryParams.start_date,
    }).then(res => res.data),
  })

  const { data: regimeBreakdown } = useQuery({
    queryKey: ['regimeBreakdown', mode, timeRange, queryParams],
    queryFn: () => performanceApi.getRegimeBreakdown({
      mode: mode || undefined,
      days: queryParams.days,
      start_date: queryParams.start_date,
    }).then(res => res.data),
  })

  // Calculate period-specific returns (for non-"all" time ranges)
  const periodMetrics = useMemo(() => {
    if (!performance?.history || performance.history.length === 0) {
      return { periodReturn: 0, periodBaselineReturn: 0, periodAlpha: 0, annualizedReturn: 0, calendarDays: 0 }
    }

    const firstSnapshot = performance.history[0]
    const lastSnapshot = performance.history[performance.history.length - 1]
    // Calculate calendar days for CAGR (standard uses 365 days/year)
    const calendarDays = calculateCalendarDays(performance.history)

    // For "all" time range, use raw cumulative returns (no normalization)
    if (timeRange === 'all') {
      const cumReturn = lastSnapshot.cumulative_return ?? 0
      const baselineReturn = lastSnapshot.baseline_return ?? 0
      const annualizedReturn = calculateAnnualizedReturn(cumReturn, calendarDays)
      return {
        periodReturn: cumReturn,
        periodBaselineReturn: baselineReturn,
        periodAlpha: cumReturn - baselineReturn,
        annualizedReturn,
        calendarDays
      }
    }

    // For other ranges, calculate period-specific returns
    const periodReturn = calculatePeriodReturn(
      lastSnapshot.cumulative_return ?? 0,
      firstSnapshot.cumulative_return ?? 0
    )
    const periodBaselineReturn = calculatePeriodReturn(
      lastSnapshot.baseline_return ?? 0,
      firstSnapshot.baseline_return ?? 0
    )
    const annualizedReturn = calculateAnnualizedReturn(periodReturn, calendarDays)

    return {
      periodReturn,
      periodBaselineReturn,
      periodAlpha: periodReturn - periodBaselineReturn,
      annualizedReturn,
      calendarDays
    }
  }, [performance?.history, timeRange])

  // Initialize chart - re-run when isLoading changes (container becomes available)
  useEffect(() => {
    if (!chartContainerRef.current) return

    // Don't create chart if it already exists
    if (chartRef.current) return

    chartRef.current = createChart(chartContainerRef.current, {
      layout: {
        background: { color: '#1e293b' },
        textColor: '#94a3b8',
      },
      grid: {
        vertLines: { color: '#334155' },
        horzLines: { color: '#334155' },
      },
      width: chartContainerRef.current.clientWidth,
      height: 300,
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        tickMarkFormatter: (time: string | number, tickMarkType: TickMarkType) => {
          // Convert time to Date object
          const date = typeof time === 'string'
            ? new Date(time)
            : new Date(time * 1000)

          const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
          const day = date.getDate()
          const month = months[date.getMonth()]
          const year = date.getFullYear()

          // Format based on tick mark type
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
        mode: 1, // Normal crosshair mode
        vertLine: {
          labelBackgroundColor: '#475569',
        },
        horzLine: {
          labelBackgroundColor: '#475569',
        },
      },
      localization: {
        priceFormatter: (price: number) => {
          const sign = price >= 0 ? '+' : ''
          return `${sign}${price.toFixed(2)}%`
        },
      },
    })

    // Portfolio equity line (blue)
    seriesRef.current = chartRef.current.addLineSeries({
      color: '#3b82f6',
      lineWidth: 2,
      title: 'Portfolio',
      priceFormat: {
        type: 'custom',
        formatter: (price: number) => {
          const sign = price >= 0 ? '+' : ''
          return `${sign}${price.toFixed(2)}%`
        },
      },
    })

    // QQQ baseline line (orange/amber)
    baselineSeriesRef.current = chartRef.current.addLineSeries({
      color: '#f59e0b',
      lineWidth: 2,
      lineStyle: 2, // Dashed line
      title: 'QQQ Baseline',
      priceFormat: {
        type: 'custom',
        formatter: (price: number) => {
          const sign = price >= 0 ? '+' : ''
          return `${sign}${price.toFixed(2)}%`
        },
      },
    })

    const handleResize = () => {
      if (chartContainerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: chartContainerRef.current.clientWidth,
        })
      }
    }

    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
      if (chartRef.current) {
        chartRef.current.remove()
        chartRef.current = null
        seriesRef.current = null
        baselineSeriesRef.current = null
      }
    }
  }, [isLoading])

  // Update chart data and formatters based on time range
  useEffect(() => {
    if (!chartRef.current || !seriesRef.current || !equityCurve?.data || equityCurve.data.length === 0) return

    const firstPoint = equityCurve.data[0]
    const firstValue = firstPoint?.value ?? 1
    const firstBaseline = firstPoint?.baseline_value ?? 1
    const isAllTime = timeRange === 'all'

    // Define formatters based on time range
    // For "all" time range: show dollar amounts
    // For other ranges: show percentage
    const priceFormatter = isAllTime
      ? (price: number) => `$${price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
      : (price: number) => {
          const sign = price >= 0 ? '+' : ''
          return `${sign}${price.toFixed(2)}%`
        }

    // Apply formatters BEFORE setting data
    chartRef.current.applyOptions({
      localization: {
        priceFormatter,
      },
    })

    seriesRef.current.applyOptions({
      priceFormat: {
        type: 'custom',
        formatter: priceFormatter,
      },
    })

    if (baselineSeriesRef.current) {
      baselineSeriesRef.current.applyOptions({
        priceFormat: {
          type: 'custom',
          formatter: priceFormatter,
        },
      })
    }

    // For "all" time range, show raw equity values (no normalization)
    // For other ranges, normalize to percentage return from start of period
    if (isAllTime) {
      // Raw equity values (no normalization)
      const chartData: LineData[] = equityCurve.data.map((point: { time: string; value: number }) => ({
        time: point.time as string,
        value: point.value,
      }))
      seriesRef.current.setData(chartData)

      // QQQ baseline data (raw values)
      if (baselineSeriesRef.current) {
        const baselineData: LineData[] = equityCurve.data
          .filter((point: { time: string; baseline_value?: number }) => point.baseline_value != null)
          .map((point: { time: string; baseline_value: number }) => ({
            time: point.time as string,
            value: point.baseline_value,
          }))
        baselineSeriesRef.current.setData(baselineData)
      }
    } else {
      // Normalized to percentage return from start of period (0% at start)
      const chartData: LineData[] = equityCurve.data.map((point: { time: string; value: number }) => ({
        time: point.time as string,
        value: firstValue > 0 ? (point.value / firstValue - 1) * 100 : 0,
      }))
      seriesRef.current.setData(chartData)

      // QQQ baseline data (normalized)
      if (baselineSeriesRef.current) {
        const baselineData: LineData[] = equityCurve.data
          .filter((point: { time: string; baseline_value?: number }) => point.baseline_value != null)
          .map((point: { time: string; baseline_value: number }) => ({
            time: point.time as string,
            value: firstBaseline > 0 ? (point.baseline_value / firstBaseline - 1) * 100 : 0,
          }))
        baselineSeriesRef.current.setData(baselineData)
      }
    }

    chartRef.current?.timeScale().fitContent()
  }, [equityCurve, timeRange])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-400"></div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">Performance</h2>

        <div className="flex gap-4">
          <select
            value={mode}
            onChange={(e) => setMode(e.target.value)}
            className="px-3 py-2 bg-slate-700 rounded-lg border border-slate-600"
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
            className="px-3 py-2 bg-slate-700 rounded-lg border border-slate-600"
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

      {/* Key Metrics */}
      {performance?.current && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
            <div className="text-sm text-gray-400 mb-1">Total Equity</div>
            <div className="text-2xl font-bold text-green-400">
              ${performance.current.total_equity?.toLocaleString() ?? '0'}
            </div>
          </div>

          <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
            <div className="text-sm text-gray-400 mb-1">{getTimeRangeLabel(timeRange)} Return</div>
            <div className={`text-2xl font-bold ${
              periodMetrics.periodReturn >= 0 ? 'text-green-400' : 'text-red-400'
            }`}>
              {periodMetrics.periodReturn >= 0 ? '+' : ''}{periodMetrics.periodReturn.toFixed(2)}%
            </div>
          </div>

          <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
            <div className="text-sm text-gray-400 mb-1">Annualized</div>
            <div className={`text-2xl font-bold ${
              periodMetrics.annualizedReturn >= 0 ? 'text-green-400' : 'text-red-400'
            }`}>
              {periodMetrics.annualizedReturn >= 0 ? '+' : ''}{periodMetrics.annualizedReturn.toFixed(2)}%
            </div>
          </div>

          <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
            <div className="text-sm text-gray-400 mb-1">Sharpe Ratio</div>
            <div className={`text-2xl font-bold ${
              (performance.current.sharpe_ratio ?? 0) >= 1 ? 'text-green-400' :
              (performance.current.sharpe_ratio ?? 0) >= 0 ? 'text-yellow-400' : 'text-red-400'
            }`}>
              {performance.current.sharpe_ratio?.toFixed(2) ?? 'N/A'}
            </div>
          </div>

          <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
            <div className="text-sm text-gray-400 mb-1">Max Drawdown</div>
            <div className="text-2xl font-bold text-red-400">
              {(performance.current.max_drawdown ?? 0).toFixed(2)}%
            </div>
          </div>
        </div>
      )}

      {/* Portfolio Holdings Breakdown */}
      {performance?.current && (
        <div className="bg-slate-800 rounded-lg p-6 border border-slate-700">
          <h3 className="text-lg font-semibold mb-4">Portfolio Holdings</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
            {/* Cash */}
            <div className="bg-slate-700/50 rounded-lg p-4">
              <div className="text-sm text-gray-400 mb-1">Cash</div>
              <div className="text-xl font-bold text-blue-400">
                ${(performance.current.cash ?? 0).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}
              </div>
              <div className="text-xs text-gray-500 mt-1">
                {(performance.current.cash_weight_pct ?? 0).toFixed(1)}%
              </div>
            </div>

            {/* Individual Holdings */}
            {performance.current.holdings?.map((holding: {
              symbol: string
              quantity: number
              value: number
              weight_pct: number
            }) => (
              <div key={holding.symbol} className="bg-slate-700/50 rounded-lg p-4">
                <div className="text-sm text-gray-400 mb-1">{holding.symbol}</div>
                <div className="text-xl font-bold text-green-400">
                  ${holding.value.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}
                </div>
                <div className="text-xs text-gray-500 mt-1">
                  {holding.quantity} shares ({holding.weight_pct.toFixed(1)}%)
                </div>
              </div>
            ))}

            {/* Show message if no holdings */}
            {(!performance.current.holdings || performance.current.holdings.length === 0) && (
              <div className="col-span-full text-center text-gray-500 py-4">
                No positions currently held
              </div>
            )}
          </div>
        </div>
      )}

      {/* Trade Statistics */}
      {performance?.current && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
            <div className="text-sm text-gray-400 mb-1">Total Trades</div>
            <div className="text-xl font-bold">{performance.current.total_trades ?? 0}</div>
          </div>

          <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
            <div className="text-sm text-gray-400 mb-1">Win Rate</div>
            <div className={`text-xl font-bold ${
              (performance.current.win_rate ?? 0) >= 0.5 ? 'text-green-400' : 'text-red-400'
            }`}>
              {((performance.current.win_rate ?? 0) * 100).toFixed(1)}%
            </div>
          </div>

          <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
            <div className="text-sm text-gray-400 mb-1">Winning Trades</div>
            <div className="text-xl font-bold text-green-400">
              {performance.current.winning_trades ?? 0}
            </div>
          </div>

          <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
            <div className="text-sm text-gray-400 mb-1">Losing Trades</div>
            <div className="text-xl font-bold text-red-400">
              {performance.current.losing_trades ?? 0}
            </div>
          </div>
        </div>
      )}

      {/* Equity Curve Chart */}
      <div className="bg-slate-800 rounded-lg p-6 border border-slate-700">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-lg font-semibold">
              {timeRange === 'all' ? 'Equity Curve' : `${getTimeRangeLabel(timeRange)} Performance`}
            </h3>
            <p className="text-sm text-gray-400">
              {timeRange === 'all'
                ? 'Absolute equity values over time'
                : 'Percentage return from start of period (both start at 0%)'}
            </p>
          </div>
          <div className="flex items-center gap-4 text-sm">
            <div className="flex items-center gap-2">
              <div className="w-4 h-0.5 bg-blue-500"></div>
              <span className="text-gray-400">Portfolio</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-4 h-0.5 bg-amber-500" style={{ borderTop: '2px dashed #f59e0b' }}></div>
              <span className="text-gray-400">QQQ Baseline</span>
            </div>
          </div>
        </div>
        <div ref={chartContainerRef} className="w-full" />
      </div>

      {/* Regime Performance Breakdown */}
      {regimeBreakdown && (() => {
        // Calculate total days across all regimes for % of time
        const totalDays = regimeBreakdown.regimes?.reduce((sum: number, r: { days?: number }) => sum + (r.days ?? 0), 0) ?? 1

        return (
          <div className="bg-slate-800 rounded-lg p-6 border border-slate-700">
            <h3 className="text-lg font-semibold mb-4">Performance by Regime</h3>

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
                    // Convert trading days to calendar days for CAGR (252 trading days ≈ 365 calendar days)
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
                        <td className="py-3 text-gray-300">
                          {tradingDays}
                        </td>
                        <td className="py-3 text-gray-300">
                          {pctOfTime.toFixed(1)}%
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )
      })()}

      {/* Performance History */}
      {performance?.history && performance.history.length > 0 && (() => {
        // Deduplicate by date - keep only the latest entry for each date
        const historyByDate = new Map<string, typeof performance.history[0]>()
        for (const snapshot of performance.history) {
          const dateKey = new Date(snapshot.timestamp).toLocaleDateString()
          // Since history is ordered by timestamp, later entries will overwrite earlier ones
          historyByDate.set(dateKey, snapshot)
        }
        const deduplicatedHistory = Array.from(historyByDate.values())

        // BUG FIX: Recalculate daily_return as true day-over-day change
        // The stored daily_return compares to the previous snapshot (same day), not previous day
        // We need to recalculate based on previous day's equity after deduplication
        const dailyReturnsMap = new Map<string, number>()
        for (let i = 0; i < deduplicatedHistory.length; i++) {
          const current = deduplicatedHistory[i]
          const currentDateKey = new Date(current.timestamp).toLocaleDateString()
          if (i === 0) {
            // First day: no previous day to compare, use stored value or 0
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
        <div className="bg-slate-800 rounded-lg p-6 border border-slate-700">
          <h3 className="text-lg font-semibold mb-4">Daily Performance</h3>

          <div className="overflow-x-auto max-h-96">
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-gray-400 border-b border-slate-700 sticky top-0 bg-slate-800">
                <tr>
                  <th className="pb-3 pr-4">Date</th>
                  <th className="pb-3 pr-4">Regime</th>
                  <th className="pb-3 pr-4">Equity</th>
                  <th className="pb-3 pr-4">Cash</th>
                  <th className="pb-3 pr-2 text-center" colSpan={2}>QQQ</th>
                  <th className="pb-3 pr-2 text-center" colSpan={2}>TQQQ</th>
                  <th className="pb-3 pr-4">Day %</th>
                  <th className="pb-3 pr-4">Cum %</th>
                  <th className="pb-3 pr-2 text-center text-amber-400" colSpan={2}>Baseline</th>
                  <th className="pb-3 pr-4">Alpha</th>
                  <th className="pb-3">DD %</th>
                </tr>
                <tr className="text-xs text-gray-500 border-b border-slate-700/50">
                  <th className="pb-2"></th>
                  <th className="pb-2"></th>
                  <th className="pb-2"></th>
                  <th className="pb-2"></th>
                  <th className="pb-2 pr-2">Qty</th>
                  <th className="pb-2 pr-2">Value</th>
                  <th className="pb-2 pr-2">Qty</th>
                  <th className="pb-2 pr-2">Value</th>
                  <th className="pb-2"></th>
                  <th className="pb-2"></th>
                  <th className="pb-2 pr-2 text-amber-400">Value</th>
                  <th className="pb-2 pr-2 text-amber-400">Return</th>
                  <th className="pb-2"></th>
                  <th className="pb-2"></th>
                </tr>
              </thead>
              <tbody>
                {deduplicatedHistory.slice().reverse().map((snapshot, idx) => {
                  // Extract position data
                  const qqqPos = snapshot.positions?.find(p => p.symbol === 'QQQ')
                  const tqqqPos = snapshot.positions?.find(p => p.symbol === 'TQQQ')
                  // Calculate alpha (strategy return - baseline return)
                  const alpha = (snapshot.cumulative_return ?? 0) - (snapshot.baseline_return ?? 0)
                  // Get the recalculated true daily return (day-over-day, not snapshot-over-snapshot)
                  const dateKey = new Date(snapshot.timestamp).toLocaleDateString()
                  const trueDailyReturn = dailyReturnsMap.get(dateKey) ?? 0

                  return (
                    <tr key={idx} className="border-b border-slate-700/50">
                      <td className="py-2 pr-4 whitespace-nowrap">
                        {new Date(snapshot.timestamp).toLocaleDateString()}
                      </td>
                      <td className="py-2 pr-4">
                        <span className="px-2 py-1 bg-slate-700 rounded text-xs whitespace-nowrap">
                          {snapshot.trend_state && snapshot.vol_state
                            ? `${snapshot.trend_state} + ${snapshot.vol_state}`
                            : snapshot.strategy_cell
                              ? `Cell ${snapshot.strategy_cell}`
                              : '-'}
                        </span>
                      </td>
                      <td className="py-2 pr-4 font-medium">
                        ${snapshot.total_equity?.toLocaleString(undefined, {minimumFractionDigits: 0, maximumFractionDigits: 0})}
                      </td>
                      <td className="py-2 pr-4 text-blue-400">
                        ${(snapshot.cash ?? 0).toLocaleString(undefined, {minimumFractionDigits: 0, maximumFractionDigits: 0})}
                      </td>
                      <td className="py-2 pr-2 text-gray-300">
                        {qqqPos?.quantity ?? 0}
                      </td>
                      <td className="py-2 pr-2 text-green-400">
                        ${(qqqPos?.value ?? 0).toLocaleString(undefined, {minimumFractionDigits: 0, maximumFractionDigits: 0})}
                      </td>
                      <td className="py-2 pr-2 text-gray-300">
                        {tqqqPos?.quantity ?? 0}
                      </td>
                      <td className="py-2 pr-2 text-green-400">
                        ${(tqqqPos?.value ?? 0).toLocaleString(undefined, {minimumFractionDigits: 0, maximumFractionDigits: 0})}
                      </td>
                      <td className={`py-2 pr-4 ${
                        trueDailyReturn >= 0 ? 'text-green-400' : 'text-red-400'
                      }`}>
                        {trueDailyReturn.toFixed(2)}%
                      </td>
                      <td className={`py-2 pr-4 ${
                        (snapshot.cumulative_return ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'
                      }`}>
                        {((snapshot.cumulative_return ?? 0)).toFixed(2)}%
                      </td>
                      <td className="py-2 pr-2 text-amber-400">
                        {snapshot.baseline_value != null
                          ? `$${snapshot.baseline_value.toLocaleString(undefined, {minimumFractionDigits: 0, maximumFractionDigits: 0})}`
                          : '-'}
                      </td>
                      <td className={`py-2 pr-2 ${
                        (snapshot.baseline_return ?? 0) >= 0 ? 'text-amber-400' : 'text-amber-600'
                      }`}>
                        {snapshot.baseline_return != null
                          ? `${snapshot.baseline_return.toFixed(2)}%`
                          : '-'}
                      </td>
                      <td className={`py-2 pr-4 font-medium ${
                        alpha >= 0 ? 'text-green-400' : 'text-red-400'
                      }`}>
                        {snapshot.baseline_return != null
                          ? `${alpha >= 0 ? '+' : ''}${alpha.toFixed(2)}%`
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
        </div>
        )
      })()}

      {/* Custom Date Range Modal */}
      {showCustomModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-slate-800 rounded-lg p-6 border border-slate-700 w-full max-w-md">
            <h3 className="text-lg font-semibold mb-4">Select Custom Date Range</h3>
            
            <div className="space-y-4">
              <div>
                <label className="block text-sm text-gray-400 mb-1">Start Date</label>
                <input
                  type="date"
                  value={customStartDate}
                  onChange={(e) => setCustomStartDate(e.target.value)}
                  className="w-full px-3 py-2 bg-slate-700 rounded-lg border border-slate-600"
                />
              </div>
              
              <div>
                <label className="block text-sm text-gray-400 mb-1">End Date (optional)</label>
                <input
                  type="date"
                  value={customEndDate}
                  onChange={(e) => setCustomEndDate(e.target.value)}
                  className="w-full px-3 py-2 bg-slate-700 rounded-lg border border-slate-600"
                  placeholder="Leave empty for today"
                />
              </div>
            </div>

            <div className="flex gap-3 mt-6">
              <button
                onClick={() => {
                  setShowCustomModal(false)
                  // Reset to 90d if no date selected
                  if (!customStartDate) {
                    setTimeRange('90d')
                  }
                }}
                className="flex-1 px-4 py-2 bg-slate-600 hover:bg-slate-500 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  setShowCustomModal(false)
                }}
                disabled={!customStartDate}
                className="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition-colors"
              >
                Apply
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default Performance
