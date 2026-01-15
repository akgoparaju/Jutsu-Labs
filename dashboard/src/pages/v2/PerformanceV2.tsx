/**
 * PerformanceV2 - Responsive Performance Page
 *
 * Fully responsive performance dashboard with charts, metrics, and tables.
 *
 * @version 2.0.0
 * @part Responsive UI - Phase 4
 */

import { useQuery } from '@tanstack/react-query'
import { useState, useEffect, useRef, useMemo } from 'react'
import { performanceApi } from '../../api/client'
import { createChart, IChartApi, ISeriesApi, LineData, TickMarkType } from 'lightweight-charts'
import { ResponsiveCard, ResponsiveText, ResponsiveGrid, MetricCard } from '../../components/ui'
import { useIsMobileOrSmaller, useIsTablet } from '../../hooks/useMediaQuery'

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

function calculateCalendarDays(history: Array<{ timestamp?: string }>): number {
  if (!history || history.length < 2) return history?.length || 0
  const firstDate = history[0].timestamp?.slice(0, 10)
  const lastDate = history[history.length - 1].timestamp?.slice(0, 10)
  if (!firstDate || !lastDate) return 0
  const start = new Date(firstDate)
  const end = new Date(lastDate)
  const diffMs = end.getTime() - start.getTime()
  return Math.floor(diffMs / (1000 * 60 * 60 * 24)) + 1
}

function PerformanceV2() {
  const isMobile = useIsMobileOrSmaller()
  const isTablet = useIsTablet()
  const [mode, setMode] = useState('')
  const [timeRange, setTimeRange] = useState<TimeRange>('90d')
  const [showCustomModal, setShowCustomModal] = useState(false)
  const [customStartDate, setCustomStartDate] = useState('')
  const [customEndDate, setCustomEndDate] = useState('')

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

  const periodMetrics = useMemo(() => {
    if (!performance?.history || performance.history.length === 0) {
      return { periodReturn: 0, periodBaselineReturn: 0, periodAlpha: 0, annualizedReturn: 0, calendarDays: 0 }
    }

    const firstSnapshot = performance.history[0]
    const lastSnapshot = performance.history[performance.history.length - 1]
    const calendarDays = calculateCalendarDays(performance.history)

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

  // Initialize chart
  useEffect(() => {
    if (!chartContainerRef.current) return
    if (chartRef.current) return

    const chartHeight = isMobile ? 250 : 300
    // Use fallback width to prevent chart creation with width 0 during layout transitions
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

    baselineSeriesRef.current = chartRef.current.addLineSeries({
      color: '#f59e0b',
      lineWidth: 2,
      lineStyle: 2,
      title: 'QQQ Baseline',
      priceFormat: {
        type: 'custom',
        formatter: (price: number) => {
          const sign = price >= 0 ? '+' : ''
          return `${sign}${price.toFixed(2)}%`
        },
      },
    })

    // Use ResizeObserver for reliable container size detection on mobile
    // This fixes blank chart issue when switching to mobile view
    const resizeObserver = new ResizeObserver((entries) => {
      if (chartContainerRef.current && chartRef.current) {
        const width = entries[0]?.contentRect.width || chartContainerRef.current.clientWidth
        if (width > 0) {
          chartRef.current.applyOptions({ width })
        }
      }
    })
    resizeObserver.observe(chartContainerRef.current)

    return () => {
      resizeObserver.disconnect()
      if (chartRef.current) {
        chartRef.current.remove()
        chartRef.current = null
        seriesRef.current = null
        baselineSeriesRef.current = null
      }
    }
  }, [isLoading, isMobile])

  // Update chart data
  useEffect(() => {
    if (!chartRef.current || !seriesRef.current || !equityCurve?.data || equityCurve.data.length === 0) return

    const firstPoint = equityCurve.data[0]
    const firstValue = firstPoint?.value ?? 1
    const firstBaseline = firstPoint?.baseline_value ?? 1
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

    seriesRef.current.applyOptions({
      priceFormat: { type: 'custom', formatter: priceFormatter },
    })

    if (baselineSeriesRef.current) {
      baselineSeriesRef.current.applyOptions({
        priceFormat: { type: 'custom', formatter: priceFormatter },
      })
    }

    if (isAllTime) {
      const chartData: LineData[] = equityCurve.data.map((point: { time: string; value: number }) => ({
        time: point.time as string,
        value: point.value,
      }))
      seriesRef.current.setData(chartData)

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
      const chartData: LineData[] = equityCurve.data.map((point: { time: string; value: number }) => ({
        time: point.time as string,
        value: firstValue > 0 ? (point.value / firstValue - 1) * 100 : 0,
      }))
      seriesRef.current.setData(chartData)

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
    <div className="space-y-4 sm:space-y-6">
      {/* Header & Controls */}
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

      {/* Key Metrics */}
      {performance?.current && (
        <ResponsiveGrid columns={{ default: 2, md: 3, lg: 5 }} gap="md">
          <MetricCard
            label="Total Equity"
            value={performance.current.total_equity ?? 0}
            format="currency"
          />
          <MetricCard
            label={`${getTimeRangeLabel(timeRange)} Return`}
            value={periodMetrics.periodReturn}
            format="percent"
          />
          <MetricCard
            label="Annualized"
            value={periodMetrics.annualizedReturn}
            format="percent"
          />
          <MetricCard
            label="Sharpe Ratio"
            value={performance.current.sharpe_ratio ?? 0}
            format="number"
          />
          <MetricCard
            label="Max Drawdown"
            value={performance.current.max_drawdown ?? 0}
            format="percent"
            className="col-span-2 md:col-span-1"
          />
        </ResponsiveGrid>
      )}

      {/* Portfolio Holdings */}
      {performance?.current && (
        <ResponsiveCard padding="md">
          <ResponsiveText variant="h2" as="h3" className="text-white mb-4">
            Portfolio Holdings
          </ResponsiveText>
          <ResponsiveGrid columns={{ default: 2, md: 4, lg: 6 }} gap="md">
            {/* Cash */}
            <div className="bg-slate-700/50 rounded-lg p-3 sm:p-4">
              <div className="text-xs sm:text-sm text-gray-400 mb-1">Cash</div>
              <div className="text-lg sm:text-xl font-bold text-blue-400">
                ${(performance.current.cash ?? 0).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}
              </div>
              <div className="text-xs text-gray-500 mt-1">
                {(performance.current.cash_weight_pct ?? 0).toFixed(1)}%
              </div>
            </div>

            {/* Holdings */}
            {performance.current.holdings?.map((holding: {
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

            {(!performance.current.holdings || performance.current.holdings.length === 0) && (
              <div className="col-span-full text-center text-gray-500 py-4">
                No positions currently held
              </div>
            )}
          </ResponsiveGrid>
        </ResponsiveCard>
      )}

      {/* Trade Statistics */}
      {performance?.current && (
        <ResponsiveGrid columns={{ default: 2, md: 4 }} gap="md">
          <MetricCard
            label="Total Trades"
            value={performance.current.total_trades ?? 0}
            format="number"
          />
          <MetricCard
            label="Win Rate"
            value={(performance.current.win_rate ?? 0) * 100}
            format="percent"
          />
          <MetricCard
            label="Winning Trades"
            value={performance.current.winning_trades ?? 0}
            format="number"
          />
          <MetricCard
            label="Losing Trades"
            value={performance.current.losing_trades ?? 0}
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
        <div ref={chartContainerRef} className="w-full" />
      </ResponsiveCard>

      {/* Regime Performance - Card View (Mobile) or Table View (Desktop) */}
      {regimeBreakdown && (() => {
        const totalDays = regimeBreakdown.regimes?.reduce((sum: number, r: { days?: number }) => sum + (r.days ?? 0), 0) ?? 1

        return (
          <ResponsiveCard padding="md">
            <ResponsiveText variant="h2" as="h3" className="text-white mb-4">
              Performance by Regime
            </ResponsiveText>

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

      {/* Daily Performance History - Simplified on Mobile */}
      {performance?.history && performance.history.length > 0 && (() => {
        // Deduplicate by date
        const historyByDate = new Map<string, typeof performance.history[0]>()
        for (const snapshot of performance.history) {
          const dateKey = new Date(snapshot.timestamp).toLocaleDateString()
          historyByDate.set(dateKey, snapshot)
        }
        const deduplicatedHistory = Array.from(historyByDate.values())

        // Recalculate daily returns
        const dailyReturnsMap = new Map<string, number>()
        for (let i = 0; i < deduplicatedHistory.length; i++) {
          const current = deduplicatedHistory[i]
          const currentDateKey = new Date(current.timestamp).toLocaleDateString()
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
            <ResponsiveText variant="h2" as="h3" className="text-white mb-4">
              Daily Performance
            </ResponsiveText>

            {isMobile ? (
              // Mobile: Simplified card view with key metrics only
              <div className="space-y-2 max-h-96 overflow-y-auto">
                {deduplicatedHistory.slice().reverse().slice(0, 30).map((snapshot, idx) => {
                  const dateKey = new Date(snapshot.timestamp).toLocaleDateString()
                  const trueDailyReturn = dailyReturnsMap.get(dateKey) ?? 0
                  const alpha = (snapshot.cumulative_return ?? 0) - (snapshot.baseline_return ?? 0)

                  return (
                    <div key={idx} className="bg-slate-700/50 rounded-lg p-3 flex items-center justify-between">
                      <div>
                        <div className="text-sm text-white">
                          {new Date(snapshot.timestamp).toLocaleDateString()}
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
                          α: {alpha >= 0 ? '+' : ''}{alpha.toFixed(2)}%
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
                      const dateKey = new Date(snapshot.timestamp).toLocaleDateString()
                      const trueDailyReturn = dailyReturnsMap.get(dateKey) ?? 0
                      const alpha = (snapshot.cumulative_return ?? 0) - (snapshot.baseline_return ?? 0)

                      return (
                        <tr key={idx} className="border-b border-slate-700/50">
                          <td className="py-2 pr-4 whitespace-nowrap">
                            {new Date(snapshot.timestamp).toLocaleDateString()}
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
                            {((snapshot.cumulative_return ?? 0)).toFixed(2)}%
                          </td>
                          {!isTablet && (
                            <td className={`py-2 pr-4 ${
                              (snapshot.baseline_return ?? 0) >= 0 ? 'text-amber-400' : 'text-amber-600'
                            }`}>
                              {snapshot.baseline_return != null
                                ? `${snapshot.baseline_return.toFixed(2)}%`
                                : '-'}
                            </td>
                          )}
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
