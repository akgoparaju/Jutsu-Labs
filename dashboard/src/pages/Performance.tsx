import { useQuery } from '@tanstack/react-query'
import { useState, useEffect, useRef } from 'react'
import { performanceApi } from '../api/client'
import { createChart, IChartApi, ISeriesApi, LineData } from 'lightweight-charts'

function Performance() {
  const [mode, setMode] = useState('')
  const [days, setDays] = useState(90)

  const chartContainerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const baselineSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)

  const { data: performance, isLoading } = useQuery({
    queryKey: ['performance', mode, days],
    queryFn: () => performanceApi.getPerformance({
      mode: mode || undefined,
      days,
    }).then(res => res.data),
  })

  const { data: equityCurve } = useQuery({
    queryKey: ['equityCurve', mode, days],
    queryFn: () => performanceApi.getEquityCurve({
      mode: mode || undefined,
      days,
    }).then(res => res.data),
  })

  const { data: regimeBreakdown } = useQuery({
    queryKey: ['regimeBreakdown', mode],
    queryFn: () => performanceApi.getRegimeBreakdown({
      mode: mode || undefined,
    }).then(res => res.data),
  })

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
      },
    })

    // Portfolio equity line (blue)
    seriesRef.current = chartRef.current.addLineSeries({
      color: '#3b82f6',
      lineWidth: 2,
      title: 'Portfolio',
    })

    // QQQ baseline line (orange/amber)
    baselineSeriesRef.current = chartRef.current.addLineSeries({
      color: '#f59e0b',
      lineWidth: 2,
      lineStyle: 2, // Dashed line
      title: 'QQQ Baseline',
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

  // Update chart data
  useEffect(() => {
    if (!seriesRef.current || !equityCurve?.data) return

    // Portfolio equity data
    const chartData: LineData[] = equityCurve.data.map((point: { time: string; value: number }) => ({
      time: point.time as string,
      value: point.value,
    }))
    seriesRef.current.setData(chartData)

    // QQQ baseline data (if available)
    if (baselineSeriesRef.current) {
      const baselineData: LineData[] = equityCurve.data
        .filter((point: { time: string; baseline_value?: number }) => point.baseline_value != null)
        .map((point: { time: string; baseline_value: number }) => ({
          time: point.time as string,
          value: point.baseline_value,
        }))
      baselineSeriesRef.current.setData(baselineData)
    }

    chartRef.current?.timeScale().fitContent()
  }, [equityCurve])

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
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="px-3 py-2 bg-slate-700 rounded-lg border border-slate-600"
          >
            <option value={7}>Last 7 Days</option>
            <option value={30}>Last 30 Days</option>
            <option value={90}>Last 90 Days</option>
            <option value={365}>Last Year</option>
          </select>
        </div>
      </div>

      {/* Key Metrics */}
      {performance?.current && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
            <div className="text-sm text-gray-400 mb-1">Total Equity</div>
            <div className="text-2xl font-bold text-green-400">
              ${performance.current.total_equity?.toLocaleString() ?? '0'}
            </div>
          </div>

          <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
            <div className="text-sm text-gray-400 mb-1">Cumulative Return</div>
            <div className={`text-2xl font-bold ${
              (performance.current.cumulative_return ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'
            }`}>
              {(performance.current.cumulative_return ?? 0).toFixed(2)}%
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
          <h3 className="text-lg font-semibold">Equity Curve</h3>
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
      {regimeBreakdown && (
        <div className="bg-slate-800 rounded-lg p-6 border border-slate-700">
          <h3 className="text-lg font-semibold mb-4">Performance by Regime</h3>

          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead className="text-sm text-gray-400 border-b border-slate-700">
                <tr>
                  <th className="pb-3">Cell</th>
                  <th className="pb-3">Trend</th>
                  <th className="pb-3">Volatility</th>
                  <th className="pb-3">Trades</th>
                  <th className="pb-3">Win Rate</th>
                  <th className="pb-3">Avg Return</th>
                  <th className="pb-3">Total Return</th>
                </tr>
              </thead>
              <tbody>
                {regimeBreakdown.regimes?.map((regime: {
                  cell: number
                  trend_state: string
                  vol_state: string
                  trade_count: number
                  win_rate: number
                  avg_return: number
                  total_return: number
                }) => (
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
                    <td className="py-3">{regime.trade_count}</td>
                    <td className={`py-3 ${
                      regime.win_rate >= 0.5 ? 'text-green-400' : 'text-red-400'
                    }`}>
                      {(regime.win_rate * 100).toFixed(1)}%
                    </td>
                    <td className={`py-3 ${
                      regime.avg_return >= 0 ? 'text-green-400' : 'text-red-400'
                    }`}>
                      {regime.avg_return.toFixed(2)}%
                    </td>
                    <td className={`py-3 ${
                      regime.total_return >= 0 ? 'text-green-400' : 'text-red-400'
                    }`}>
                      {regime.total_return.toFixed(2)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

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
                        (snapshot.daily_return ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'
                      }`}>
                        {((snapshot.daily_return ?? 0)).toFixed(2)}%
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
    </div>
  )
}

export default Performance
