import { useStatus, useRegime, useIndicators, useStartEngine, useStopEngine, useSwitchMode } from '../hooks/useStatus'
import { useState, useMemo } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ExecuteTradeModal } from '../components/ExecuteTradeModal'
import { SchedulerControl } from '../components/SchedulerControl'
import { SchwabTokenBanner } from '../components/SchwabTokenBanner'
import { performanceApi } from '../api/client'
import { useAuth } from '../contexts/AuthContext'

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

function Dashboard() {
  const { data: status, isLoading: statusLoading } = useStatus()
  const { data: regime } = useRegime()
  const { data: indicators } = useIndicators()
  const startEngine = useStartEngine()
  const stopEngine = useStopEngine()
  const switchMode = useSwitchMode()
  const queryClient = useQueryClient()
  const { hasPermission } = useAuth()

  // Time range state for portfolio metrics
  const [timeRange, setTimeRange] = useState<DashboardTimeRange>('90d')

  // Calculate query params based on time range
  const queryParams = useMemo(() => getTimeRangeParams(timeRange), [timeRange])

  // Fetch performance data for baseline values
  const { data: performanceData } = useQuery({
    queryKey: ['performance', '', queryParams.days, queryParams.start_date],
    queryFn: () => performanceApi.getPerformance({
      days: queryParams.days,
      start_date: queryParams.start_date
    }).then(res => res.data),
    refetchInterval: 30000, // Refresh every 30 seconds
  })

  // Get latest baseline from most recent snapshot
  const latestSnapshot = performanceData?.history?.[performanceData.history.length - 1]
  const baselineValue = latestSnapshot?.baseline_value

  // Calculate period-specific returns
  const periodMetrics = useMemo(() => {
    if (!performanceData?.history || performanceData.history.length === 0) {
      return { periodReturn: 0, periodBaselineReturn: 0, periodAlpha: 0, annualizedReturn: 0, baselineAnnualizedReturn: 0, calendarDays: 0 }
    }

    const firstSnapshot = performanceData.history[0]
    const lastSnapshot = performanceData.history[performanceData.history.length - 1]
    // Calculate calendar days for CAGR (standard uses 365 days/year)
    const calendarDays = calculateCalendarDays(performanceData.history)

    // For "all" time range, use raw cumulative returns (no normalization)
    if (timeRange === 'all') {
      const cumReturn = lastSnapshot.cumulative_return ?? 0
      const baseReturn = lastSnapshot.baseline_return ?? 0
      const annualizedReturn = calculateAnnualizedReturn(cumReturn, calendarDays)
      const baselineAnnualizedReturn = calculateAnnualizedReturn(baseReturn, calendarDays)
      return {
        periodReturn: cumReturn,
        periodBaselineReturn: baseReturn,
        periodAlpha: cumReturn - baseReturn,
        annualizedReturn,
        baselineAnnualizedReturn,
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
    const baselineAnnualizedReturn = calculateAnnualizedReturn(periodBaselineReturn, calendarDays)

    return {
      periodReturn,
      periodBaselineReturn,
      periodAlpha: periodReturn - periodBaselineReturn,
      annualizedReturn,
      baselineAnnualizedReturn,
      calendarDays
    }
  }, [performanceData?.history, timeRange])

  const [confirmLive, setConfirmLive] = useState(false)
  const [showTradeModal, setShowTradeModal] = useState(false)

  // Extract currentCell for use in Target Allocation (extracted from Decision Tree IIFE)
  const currentCell = indicators?.indicators?.find(i => i.name === 'current_cell')?.value

  const handleTradeSuccess = () => {
    // Refresh status and trades data after successful trade
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
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">Jutsu Trader</h2>
{hasPermission('trades:execute') && (
          <button
            onClick={() => setShowTradeModal(true)}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors font-medium"
          >
            Execute Trade
          </button>
        )}
      </div>

      {/* Schwab Token Status Banner - Admin Only (viewers don't need to see token warnings) */}
      {hasPermission('config:write') && <SchwabTokenBanner hideWhenHealthy={true} />}

      {/* Execute Trade Modal */}
      <ExecuteTradeModal
        isOpen={showTradeModal}
        onClose={() => setShowTradeModal(false)}
        onSuccess={handleTradeSuccess}
      />

      {/* 1. Engine Control - Admin Only */}
      {hasPermission('engine:control') && (
        <div className="bg-slate-800 rounded-lg p-6 border border-slate-700">
          <h3 className="text-lg font-semibold mb-4">Engine Control</h3>

          <div className="flex items-center gap-4 mb-4">
            <div className="flex items-center gap-2">
              <span className={`w-3 h-3 rounded-full ${
                status?.is_running ? 'bg-green-500 animate-pulse' : 'bg-gray-500'
              }`} />
              <span className="font-medium">
                {status?.is_running ? 'Running' : 'Stopped'}
              </span>
            </div>

            <div className="px-3 py-1 rounded-full text-sm font-medium bg-slate-700">
              Mode: {status?.mode === 'online_live' ? 'Live Trading' : status?.mode === 'offline_mock' ? 'Paper Trading' : status?.mode || 'N/A'}
            </div>

            {status?.uptime_seconds && (
              <div className="text-sm text-gray-400">
                Uptime: {Math.floor(status.uptime_seconds / 60)}m {Math.floor(status.uptime_seconds % 60)}s
              </div>
            )}
          </div>

          <div className="flex gap-3">
            {!status?.is_running ? (
              <>
                <button
                  onClick={() => handleStart('offline_mock')}
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors"
                >
                  Start Paper Trading
                </button>
                <button
                  onClick={() => handleStart('online_live')}
                  className="px-4 py-2 bg-yellow-600 hover:bg-yellow-700 rounded-lg transition-colors"
                >
                  Start Live Trading
                </button>
              </>
            ) : (
              <>
                <button
                  onClick={handleStop}
                  className="px-4 py-2 bg-red-600 hover:bg-red-700 rounded-lg transition-colors"
                >
                  Stop Engine
                </button>
                <select
                  value={status?.mode || ''}
                  onChange={(e) => handleModeSwitch(e.target.value)}
                  className="px-4 py-2 bg-slate-700 rounded-lg border border-slate-600"
                >
                  <option value="offline_mock">Paper Trading</option>
                  <option value="online_live">Live Trading</option>
                </select>
              </>
            )}
          </div>

          {confirmLive && (
            <div className="mt-4 p-4 bg-yellow-900/30 border border-yellow-600 rounded-lg">
              <p className="text-yellow-400 font-medium mb-2">
                Warning: Live trading will execute real orders with real money!
              </p>
              <div className="flex gap-3">
                <button
                  onClick={() => {
                    startEngine.mutate({ mode: 'online_live', confirm: true })
                    setConfirmLive(false)
                  }}
                  className="px-4 py-2 bg-yellow-600 hover:bg-yellow-700 rounded-lg"
                >
                  Confirm Live Trading
                </button>
                <button
                  onClick={() => setConfirmLive(false)}
                  className="px-4 py-2 bg-slate-600 hover:bg-slate-700 rounded-lg"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* 2. Portfolio Returns - with time range filter */}
      {status?.portfolio && (
        <div className="bg-slate-800 rounded-lg p-6 border border-slate-700">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold">Portfolio Returns</h3>

            {/* Time Range Segmented Buttons */}
            <div className="flex bg-slate-700/50 rounded-lg p-1">
              {(['90d', 'ytd', '1y', 'all'] as DashboardTimeRange[]).map((range) => (
                <button
                  key={range}
                  onClick={() => setTimeRange(range)}
                  className={`px-3 py-1.5 text-sm font-medium rounded-md transition-all ${
                    timeRange === range
                      ? 'bg-blue-600 text-white shadow-sm'
                      : 'text-gray-400 hover:text-white hover:bg-slate-600/50'
                  }`}
                >
                  {range === '90d' ? '90D' : range === 'ytd' ? 'YTD' : range === '1y' ? '1Y' : 'All'}
                </button>
              ))}
            </div>
          </div>

          {/* Period Returns */}
          <div className="text-xs text-gray-500 uppercase tracking-wider mb-2">{getTimeRangeLabel(timeRange)} Returns</div>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <div className="bg-slate-700/50 rounded-lg p-4">
              <div className="text-sm text-gray-400 mb-1">Portfolio</div>
              <div className={`text-2xl font-bold ${periodMetrics.periodReturn >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {periodMetrics.periodReturn >= 0 ? '+' : ''}{periodMetrics.periodReturn.toFixed(2)}%
              </div>
            </div>

            <div className="bg-slate-700/50 rounded-lg p-4">
              <div className="text-sm text-gray-400 mb-1">Portfolio CAGR</div>
              <div className={`text-2xl font-bold ${periodMetrics.annualizedReturn >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {periodMetrics.annualizedReturn >= 0 ? '+' : ''}{periodMetrics.annualizedReturn.toFixed(2)}%
              </div>
            </div>

            <div className="bg-slate-700/50 rounded-lg p-4 border border-amber-600/30">
              <div className="text-sm text-amber-400 mb-1">QQQ Baseline</div>
              <div className={`text-2xl font-bold ${periodMetrics.periodBaselineReturn >= 0 ? 'text-amber-400' : 'text-amber-600'}`}>
                {periodMetrics.periodBaselineReturn >= 0 ? '+' : ''}{periodMetrics.periodBaselineReturn.toFixed(2)}%
              </div>
            </div>

            <div className="bg-slate-700/50 rounded-lg p-4 border border-amber-600/30">
              <div className="text-sm text-amber-400 mb-1">Baseline CAGR</div>
              <div className={`text-2xl font-bold ${periodMetrics.baselineAnnualizedReturn >= 0 ? 'text-amber-400' : 'text-amber-600'}`}>
                {periodMetrics.baselineAnnualizedReturn >= 0 ? '+' : ''}{periodMetrics.baselineAnnualizedReturn.toFixed(2)}%
              </div>
            </div>

            <div className="bg-slate-700/50 rounded-lg p-4">
              <div className="text-sm text-gray-400 mb-1">Alpha</div>
              <div className={`text-2xl font-bold ${periodMetrics.periodAlpha >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {periodMetrics.periodAlpha >= 0 ? '+' : ''}{periodMetrics.periodAlpha.toFixed(2)}%
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 3. Portfolio Snapshot - current values only */}
      {status?.portfolio && (
        <div className="bg-slate-800 rounded-lg p-6 border border-slate-700">
          <h3 className="text-lg font-semibold mb-4">Portfolio Snapshot</h3>

          {/* Account Balances */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
            <div className="bg-slate-700/50 rounded-lg p-4">
              <div className="text-sm text-gray-400 mb-1">Total Equity</div>
              <div className="text-2xl font-bold text-green-400">
                ${status.portfolio.total_equity?.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2}) ?? '0'}
              </div>
            </div>

            <div className="bg-slate-700/50 rounded-lg p-4 border border-amber-600/30">
              <div className="text-sm text-amber-400 mb-1">QQQ Baseline</div>
              <div className="text-2xl font-bold text-amber-400">
                ${baselineValue?.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2}) ?? 'N/A'}
              </div>
            </div>

            {status.portfolio.cash !== undefined && (
              <div className="bg-slate-700/50 rounded-lg p-4">
                <div className="text-sm text-gray-400 mb-1">Cash</div>
                <div className="text-2xl font-bold">
                  ${status.portfolio.cash?.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}
                </div>
              </div>
            )}

            {status.portfolio.positions_value !== undefined && (
              <div className="bg-slate-700/50 rounded-lg p-4">
                <div className="text-sm text-gray-400 mb-1">Positions Value</div>
                <div className="text-2xl font-bold">
                  ${status.portfolio.positions_value?.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}
                </div>
              </div>
            )}
          </div>

          {/* Positions Table */}
          {status.portfolio.positions && status.portfolio.positions.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead className="text-sm text-gray-400 border-b border-slate-700">
                  <tr>
                    <th className="pb-3">Symbol</th>
                    <th className="pb-3">Quantity</th>
                    <th className="pb-3">Avg Cost</th>
                    <th className="pb-3">Market Value</th>
                    <th className="pb-3">P&L</th>
                    <th className="pb-3">Weight</th>
                  </tr>
                </thead>
                <tbody>
                  {status.portfolio.positions.map((pos) => {
                    // Calculate P&L from avg_cost and market_value if available
                    const costBasis = pos.avg_cost && pos.quantity ? pos.avg_cost * pos.quantity : null
                    const pnl = pos.unrealized_pnl ?? (costBasis && pos.market_value ? pos.market_value - costBasis : null)
                    const pnlPct = costBasis && pnl ? (pnl / costBasis) * 100 : null

                    return (
                      <tr key={pos.symbol} className="border-b border-slate-700/50">
                        <td className="py-3 font-medium">{pos.symbol}</td>
                        <td className="py-3">{pos.quantity}</td>
                        <td className="py-3">${pos.avg_cost?.toFixed(2) ?? 'N/A'}</td>
                        <td className="py-3">${pos.market_value?.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2}) ?? 'N/A'}</td>
                        <td className={`py-3 ${(pnl ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                          {pnl != null ? (
                            <span>
                              ${pnl.toFixed(2)}
                              {pnlPct != null && <span className="text-xs ml-1">({pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(1)}%)</span>}
                            </span>
                          ) : 'N/A'}
                        </td>
                        <td className="py-3">{pos.weight_pct?.toFixed(1)}%</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* 4. Current Regime - Z-Score removed */}
      <div className="bg-slate-800 rounded-lg p-6 border border-slate-700">
        <h3 className="text-lg font-semibold mb-4">Current Regime</h3>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="bg-slate-700/50 rounded-lg p-4">
            <div className="text-sm text-gray-400 mb-1">Strategy Cell</div>
            <div className="text-2xl font-bold text-blue-400">
              {regime?.cell ?? status?.regime?.cell ?? 'N/A'}
            </div>
          </div>

          <div className="bg-slate-700/50 rounded-lg p-4">
            <div className="text-sm text-gray-400 mb-1">Trend State</div>
            <div className={`text-2xl font-bold ${
              (regime?.trend_state || status?.regime?.trend_state) === 'BULLISH' ? 'text-green-400' :
              (regime?.trend_state || status?.regime?.trend_state) === 'BEARISH' ? 'text-red-400' :
              'text-yellow-400'
            }`}>
              {regime?.trend_state ?? status?.regime?.trend_state ?? 'N/A'}
            </div>
          </div>

          <div className="bg-slate-700/50 rounded-lg p-4">
            <div className="text-sm text-gray-400 mb-1">Volatility State</div>
            <div className={`text-2xl font-bold ${
              (regime?.vol_state || status?.regime?.vol_state) === 'LOW' ? 'text-green-400' :
              (regime?.vol_state || status?.regime?.vol_state) === 'HIGH' ? 'text-red-400' :
              'text-yellow-400'
            }`}>
              {regime?.vol_state ?? status?.regime?.vol_state ?? 'N/A'}
            </div>
          </div>
        </div>
      </div>

      {/* 5. Decision Tree - Target Allocation extracted */}
      {indicators?.indicators && indicators.indicators.length > 0 && (() => {
        // Helper function to extract indicator by name
        const getIndicator = (name: string) =>
          indicators.indicators?.find(i => i.name === name);

        const tNorm = getIndicator('t_norm')?.value;
        const zScore = getIndicator('z_score')?.value;
        const trendState = getIndicator('trend_state')?.signal;
        const volState = getIndicator('vol_state')?.signal;
        const smaFast = getIndicator('sma_fast')?.value;
        const smaSlow = getIndicator('sma_slow')?.value;
        const volCrushTriggered = getIndicator('vol_crush_triggered')?.value;
        const bondSmaFast = getIndicator('bond_sma_fast')?.value;
        const bondSmaSlow = getIndicator('bond_sma_slow')?.value;
        const bondTrend = getIndicator('bond_trend')?.signal;

        // String values from signal property
        const trendStateStr = trendState ?? 'N/A';
        const volStateStr = volState ?? 'N/A';
        const bondTrendStr = bondTrend ?? 'N/A';

        // Determine SMA structure
        const smaStructure = smaFast && smaSlow
          ? smaFast > smaSlow ? 'Bull (Fast > Slow)' : 'Bear (Fast < Slow)'
          : 'N/A';

        // Check if in defensive cells (4, 5, or 6)
        const isDefensiveCell = currentCell === 4 || currentCell === 5 || currentCell === 6;

        return (
          <div className="bg-slate-800 rounded-lg p-6 border border-slate-700">
            <h3 className="text-lg font-semibold mb-4">
              Decision Tree
              <span className="text-sm font-normal text-gray-400 ml-2">
                ({indicators.symbol})
              </span>
            </h3>

            <div className="space-y-4">
              {/* Trend Classification Box */}
              <div className="bg-slate-700/50 rounded-lg p-4">
                <h4 className="text-md font-semibold mb-3 text-blue-400">TREND CLASSIFICATION</h4>
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-gray-400">T_norm (Kalman):</span>
                    <span className={`font-bold ${
                      typeof tNorm === 'number'
                        ? tNorm > 0.3 ? 'text-green-400'
                        : tNorm < -0.3 ? 'text-red-400'
                        : 'text-yellow-400'
                        : ''
                    }`}>
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
                    <span className={`font-bold ${
                      smaStructure.startsWith('Bull') ? 'text-green-400'
                      : smaStructure.startsWith('Bear') ? 'text-red-400'
                      : ''
                    }`}>
                      {smaStructure}
                    </span>
                  </div>
                  <div className="border-t border-slate-600 my-2"></div>
                  <div className="flex justify-between items-center">
                    <span className="text-gray-400">→ Trend State:</span>
                    <span className={`text-xl font-bold ${
                      trendStateStr === 'BullStrong' ? 'text-green-400'
                      : trendStateStr === 'BearStrong' ? 'text-red-400'
                      : 'text-yellow-400'
                    }`}>
                      {trendStateStr || 'N/A'}
                    </span>
                  </div>
                </div>
              </div>

              {/* Volatility Classification Box */}
              <div className="bg-slate-700/50 rounded-lg p-4">
                <h4 className="text-md font-semibold mb-3 text-purple-400">VOLATILITY CLASSIFICATION</h4>
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-gray-400">Z-Score:</span>
                    <span className={`font-bold ${
                      typeof zScore === 'number'
                        ? zScore > 1.0 ? 'text-red-400'
                        : zScore < 0.2 ? 'text-green-400'
                        : 'text-yellow-400'
                        : ''
                    }`}>
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
                    <span className={`font-bold ${volCrushTriggered === 1 ? 'text-red-400' : 'text-gray-400'}`}>
                      {volCrushTriggered === 1 ? 'ACTIVE' : 'Inactive'}
                    </span>
                  </div>
                  <div className="border-t border-slate-600 my-2"></div>
                  <div className="flex justify-between items-center">
                    <span className="text-gray-400">→ Vol State:</span>
                    <span className={`text-xl font-bold ${
                      volStateStr === 'Low' ? 'text-green-400'
                      : volStateStr === 'High' ? 'text-red-400'
                      : 'text-yellow-400'
                    }`}>
                      {volStateStr || 'N/A'}
                    </span>
                  </div>
                </div>
              </div>

              {/* Treasury Overlay Box - Only show if in defensive cells */}
              {isDefensiveCell && bondSmaFast !== null && bondSmaFast !== undefined && bondSmaSlow !== null && bondSmaSlow !== undefined && (
                <div className="bg-slate-700/50 rounded-lg p-4">
                  <h4 className="text-md font-semibold mb-3 text-yellow-400">TREASURY OVERLAY (Active)</h4>
                  <div className="space-y-2 text-sm">
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
                      <span className={`text-xl font-bold ${
                        bondTrendStr === 'Bull' ? 'text-green-400'
                        : bondTrendStr === 'Bear' ? 'text-red-400'
                        : 'text-yellow-400'
                      }`}>
                        {bondTrendStr || 'N/A'} → {bondTrendStr === 'Bull' ? 'TMF' : 'TMV'}
                      </span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        );
      })()}

      {/* 6. Target Allocation - extracted as separate block */}
      {indicators?.target_allocation && (
        <div className="bg-slate-800 rounded-lg p-6 border border-slate-700">
          <h3 className="text-lg font-semibold mb-4 text-green-400">
            Target Allocation {currentCell ? `(Cell ${currentCell})` : ''}
          </h3>
          <div className="space-y-3">
            {Object.entries(indicators.target_allocation).map(([symbol, pct]) => {
              const percentage = typeof pct === 'number' ? pct : 0;
              const barWidth = `${percentage}%`;

              return (
                <div key={symbol}>
                  <div className="flex justify-between text-sm mb-1">
                    <span className="text-gray-400">{symbol}:</span>
                    <span className="font-bold">{percentage.toFixed(0)}%</span>
                  </div>
                  <div className="w-full bg-slate-600 rounded-full h-2">
                    <div
                      className={`h-2 rounded-full ${
                        percentage > 0
                          ? symbol.includes('TQQQ') || symbol.includes('QQQ') ? 'bg-green-500'
                          : symbol.includes('PSQ') ? 'bg-red-500'
                          : symbol.includes('TMF') ? 'bg-blue-500'
                          : symbol.includes('TMV') ? 'bg-yellow-500'
                          : 'bg-gray-500'
                          : 'bg-transparent'
                      }`}
                      style={{ width: barWidth }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* 7. Execution Schedule - Admin Only */}
      {hasPermission('scheduler:control') && (status?.last_execution || status?.next_execution) && (
        <div className="bg-slate-800 rounded-lg p-6 border border-slate-700">
          <h3 className="text-lg font-semibold mb-4">Execution Schedule</h3>

          <div className="grid grid-cols-2 gap-4">
            {status.last_execution && (
              <div className="bg-slate-700/50 rounded-lg p-4">
                <div className="text-sm text-gray-400 mb-1">Last Execution</div>
                <div className="text-lg">
                  {new Date(status.last_execution).toLocaleString()}
                </div>
              </div>
            )}

            {status.next_execution && (
              <div className="bg-slate-700/50 rounded-lg p-4">
                <div className="text-sm text-gray-400 mb-1">Next Execution</div>
                <div className="text-lg">
                  {new Date(status.next_execution).toLocaleString()}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Error Display */}
      {status?.error && (
        <div className="bg-red-900/30 border border-red-600 rounded-lg p-4">
          <h3 className="text-red-400 font-medium mb-2">Error</h3>
          <p className="text-red-300">{status.error}</p>
        </div>
      )}

      {/* 8. Scheduler Control - Admin Only */}
      {hasPermission('scheduler:control') && <SchedulerControl />}
    </div>
  )
}

export default Dashboard
