/**
 * TradesV2 - Responsive Trades Page
 *
 * Fully responsive trade history with table/card views, filters, and pagination.
 *
 * @version 2.0.0
 * @part Responsive UI - Phase 4
 */

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { tradesApi, TradeRecord } from '../../api/client'
import { ExecuteTradeModal } from '../../components/ExecuteTradeModal'
import { ResponsiveCard, ResponsiveText, ResponsiveGrid, MetricCard } from '../../components/ui'
import { useIsMobileOrSmaller } from '../../hooks/useMediaQuery'
import { useAuth } from '../../contexts/AuthContext'

function TradesV2() {
  const queryClient = useQueryClient()
  const isMobile = useIsMobileOrSmaller()
  const { hasPermission } = useAuth()
  const [page, setPage] = useState(1)
  const [pageSize] = useState(20)
  const [filters, setFilters] = useState({
    symbol: '',
    mode: '',
    action: '',
  })
  const [showTradeModal, setShowTradeModal] = useState(false)

  const handleTradeSuccess = () => {
    queryClient.invalidateQueries({ queryKey: ['trades'] })
    queryClient.invalidateQueries({ queryKey: ['tradeStats'] })
  }

  const { data, isLoading, error } = useQuery({
    queryKey: ['trades', page, pageSize, filters],
    queryFn: () => tradesApi.getTrades({
      page,
      page_size: pageSize,
      symbol: filters.symbol || undefined,
      mode: filters.mode || undefined,
      action: filters.action || undefined,
    }).then(res => res.data),
  })

  const { data: stats } = useQuery({
    queryKey: ['tradeStats', filters.mode],
    queryFn: () => tradesApi.getStats({
      mode: filters.mode || undefined,
    }).then(res => res.data),
  })

  const handleExport = async () => {
    try {
      const response = await tradesApi.exportCsv({
        symbol: filters.symbol || undefined,
        mode: filters.mode || undefined,
        action: filters.action || undefined,
      })

      const url = window.URL.createObjectURL(response.data)
      const a = document.createElement('a')
      a.href = url
      a.download = `trades_${new Date().toISOString().split('T')[0]}.csv`
      document.body.appendChild(a)
      a.click()
      window.URL.revokeObjectURL(url)
      a.remove()
    } catch (err) {
      console.error('Export failed:', err)
    }
  }

  return (
    <div className="space-y-4 sm:space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <ResponsiveText variant="h1" as="h2" className="text-white">
          Trade History
        </ResponsiveText>
        <div className="flex gap-2 sm:gap-3">
          {hasPermission('trades:execute') && (
            <button
              onClick={() => setShowTradeModal(true)}
              className="flex-1 sm:flex-none px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors font-medium min-h-[44px]"
            >
              Execute Trade
            </button>
          )}
          <button
            onClick={handleExport}
            className="flex-1 sm:flex-none px-4 py-2 bg-green-600 hover:bg-green-700 rounded-lg transition-colors min-h-[44px]"
          >
            Export CSV
          </button>
        </div>
      </div>

      {/* Execute Trade Modal */}
      <ExecuteTradeModal
        isOpen={showTradeModal}
        onClose={() => setShowTradeModal(false)}
        onSuccess={handleTradeSuccess}
      />

      {/* Trade Statistics */}
      {stats && (
        <ResponsiveGrid columns={{ default: 2, md: 3, lg: 5 }} gap="md">
          <MetricCard
            label="Total Trades"
            value={stats.total_trades ?? 0}
            format="number"
          />
          <MetricCard
            label="Win Rate"
            value={(stats.win_rate ?? 0) * 100}
            format="percent"
          />
          <MetricCard
            label="Avg Slippage"
            value={stats.avg_slippage_pct ?? 0}
            format="percent"
            variant="default"
          />
          <MetricCard
            label="Total Volume"
            value={stats.total_volume ?? 0}
            format="currency"
          />
          <MetricCard
            label="Net P&L"
            value={stats.net_pnl ?? 0}
            format="currency"
            className="col-span-2 md:col-span-1"
          />
        </ResponsiveGrid>
      )}

      {/* Filters */}
      <ResponsiveCard padding="md">
        <div className="flex flex-col sm:flex-row flex-wrap gap-3 sm:gap-4">
          <div className="flex-1 min-w-0 sm:min-w-[150px] sm:max-w-[200px]">
            <label className="block text-sm text-gray-400 mb-1">Symbol</label>
            <input
              type="text"
              value={filters.symbol}
              onChange={(e) => setFilters({ ...filters, symbol: e.target.value })}
              placeholder="e.g., QQQ"
              className="w-full px-3 py-2 bg-slate-700 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500 min-h-[44px]"
            />
          </div>
          <div className="flex-1 min-w-0 sm:min-w-[150px] sm:max-w-[200px]">
            <label className="block text-sm text-gray-400 mb-1">Mode</label>
            <select
              value={filters.mode}
              onChange={(e) => setFilters({ ...filters, mode: e.target.value })}
              className="w-full px-3 py-2 bg-slate-700 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500 min-h-[44px]"
            >
              <option value="">All Modes</option>
              <option value="offline_mock">Offline Mock</option>
              <option value="online_mock">Online Mock</option>
              <option value="online_live">Online Live</option>
            </select>
          </div>
          <div className="flex-1 min-w-0 sm:min-w-[150px] sm:max-w-[200px]">
            <label className="block text-sm text-gray-400 mb-1">Action</label>
            <select
              value={filters.action}
              onChange={(e) => setFilters({ ...filters, action: e.target.value })}
              className="w-full px-3 py-2 bg-slate-700 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500 min-h-[44px]"
            >
              <option value="">All Actions</option>
              <option value="BUY">Buy</option>
              <option value="SELL">Sell</option>
            </select>
          </div>
          <div className="flex items-end">
            <button
              onClick={() => setFilters({ symbol: '', mode: '', action: '' })}
              className="w-full sm:w-auto px-3 py-2 bg-slate-600 hover:bg-slate-500 rounded-lg transition-colors min-h-[44px]"
            >
              Clear Filters
            </button>
          </div>
        </div>
      </ResponsiveCard>

      {/* Trades - Card View (Mobile) or Table View (Desktop) */}
      {isLoading ? (
        <div className="flex items-center justify-center h-64">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-400"></div>
        </div>
      ) : error ? (
        <ResponsiveCard padding="md">
          <div className="p-6 text-center text-red-400">
            Failed to load trades
          </div>
        </ResponsiveCard>
      ) : data?.trades && data.trades.length > 0 ? (
        <>
          {isMobile ? (
            // Mobile Card View
            <div className="space-y-3">
              {data.trades.map((trade: TradeRecord) => (
                <ResponsiveCard key={trade.id} padding="md">
                  <div className="space-y-3">
                    {/* Header: Symbol, Action, Mode */}
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-white">{trade.symbol}</span>
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                          trade.action === 'BUY' ? 'bg-green-600/30 text-green-400' : 'bg-red-600/30 text-red-400'
                        }`}>
                          {trade.action}
                        </span>
                      </div>
                      <span className={`px-2 py-0.5 rounded text-xs ${
                        trade.mode === 'online_live' ? 'bg-yellow-600/30 text-yellow-400' :
                        trade.mode === 'online_mock' ? 'bg-purple-600/30 text-purple-400' :
                        'bg-blue-600/30 text-blue-400'
                      }`}>
                        {trade.mode}
                      </span>
                    </div>

                    {/* Trade Details Grid */}
                    <div className="grid grid-cols-2 gap-2 text-sm">
                      <div>
                        <span className="text-gray-400 block">Quantity</span>
                        <span className="text-white">{trade.quantity}</span>
                      </div>
                      <div>
                        <span className="text-gray-400 block">Cell</span>
                        <span className="px-2 py-0.5 bg-slate-700 rounded text-xs">
                          {trade.strategy_cell ?? '-'}
                        </span>
                      </div>
                      <div>
                        <span className="text-gray-400 block">Target</span>
                        <span className="text-white">${trade.target_price.toFixed(2)}</span>
                      </div>
                      <div>
                        <span className="text-gray-400 block">Fill</span>
                        <span className="text-white">
                          {trade.fill_price ? `$${trade.fill_price.toFixed(2)}` : '-'}
                        </span>
                      </div>
                    </div>

                    {/* Slippage & Time */}
                    <div className="flex items-center justify-between text-sm border-t border-slate-700/50 pt-2">
                      <span className={`${(trade.slippage_pct ?? 0) > 0.1 ? 'text-yellow-400' : 'text-gray-400'}`}>
                        Slippage: {trade.slippage_pct !== undefined ? `${trade.slippage_pct.toFixed(3)}%` : '-'}
                      </span>
                      <span className="text-gray-400">
                        {new Date(trade.timestamp).toLocaleDateString()}
                      </span>
                    </div>

                    {/* Reason */}
                    {trade.reason && (
                      <div className="text-sm text-gray-400 border-t border-slate-700/50 pt-2">
                        <span className="text-gray-500">Reason:</span> {trade.reason}
                      </div>
                    )}
                  </div>
                </ResponsiveCard>
              ))}
            </div>
          ) : (
            // Desktop Table View
            <ResponsiveCard padding="none">
              <div className="overflow-x-auto">
                <table className="w-full text-left">
                  <thead className="text-sm text-gray-400 bg-slate-700/50">
                    <tr>
                      <th className="px-4 py-3">Time</th>
                      <th className="px-4 py-3">Symbol</th>
                      <th className="px-4 py-3">Action</th>
                      <th className="px-4 py-3">Quantity</th>
                      <th className="px-4 py-3">Target</th>
                      <th className="px-4 py-3">Fill</th>
                      <th className="px-4 py-3">Slippage</th>
                      <th className="px-4 py-3">Cell</th>
                      <th className="px-4 py-3">Mode</th>
                      <th className="px-4 py-3">Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.trades.map((trade: TradeRecord) => (
                      <tr key={trade.id} className="border-t border-slate-700/50 hover:bg-slate-700/30">
                        <td className="px-4 py-3 text-sm">
                          {new Date(trade.timestamp).toLocaleString()}
                        </td>
                        <td className="px-4 py-3 font-medium">{trade.symbol}</td>
                        <td className={`px-4 py-3 font-medium ${
                          trade.action === 'BUY' ? 'text-green-400' : 'text-red-400'
                        }`}>
                          {trade.action}
                        </td>
                        <td className="px-4 py-3">{trade.quantity}</td>
                        <td className="px-4 py-3">${trade.target_price.toFixed(2)}</td>
                        <td className="px-4 py-3">
                          {trade.fill_price ? `$${trade.fill_price.toFixed(2)}` : '-'}
                        </td>
                        <td className={`px-4 py-3 ${
                          (trade.slippage_pct ?? 0) > 0.1 ? 'text-yellow-400' : ''
                        }`}>
                          {trade.slippage_pct !== undefined ? `${trade.slippage_pct.toFixed(3)}%` : '-'}
                        </td>
                        <td className="px-4 py-3">
                          <span className="px-2 py-1 bg-slate-700 rounded text-xs">
                            {trade.strategy_cell ?? '-'}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <span className={`px-2 py-1 rounded text-xs ${
                            trade.mode === 'online_live' ? 'bg-yellow-600/30 text-yellow-400' :
                            trade.mode === 'online_mock' ? 'bg-purple-600/30 text-purple-400' :
                            'bg-blue-600/30 text-blue-400'
                          }`}>
                            {trade.mode}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-400 max-w-xs truncate">
                          {trade.reason || '-'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </ResponsiveCard>
          )}

          {/* Pagination */}
          <div className="flex flex-col sm:flex-row items-center justify-between gap-3 px-1">
            <div className="text-sm text-gray-400 text-center sm:text-left">
              {isMobile ? (
                `${page} / ${data.total_pages}`
              ) : (
                `Showing ${((page - 1) * pageSize) + 1} to ${Math.min(page * pageSize, data.total)} of ${data.total} trades`
              )}
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={page === 1}
                className="px-4 py-2 bg-slate-600 hover:bg-slate-500 rounded disabled:opacity-50 disabled:cursor-not-allowed min-h-[44px]"
              >
                Previous
              </button>
              {!isMobile && (
                <span className="px-4 py-2 bg-slate-700 rounded min-h-[44px] flex items-center">
                  Page {page} of {data.total_pages}
                </span>
              )}
              <button
                onClick={() => setPage(p => Math.min(data.total_pages, p + 1))}
                disabled={page >= data.total_pages}
                className="px-4 py-2 bg-slate-600 hover:bg-slate-500 rounded disabled:opacity-50 disabled:cursor-not-allowed min-h-[44px]"
              >
                Next
              </button>
            </div>
          </div>
        </>
      ) : (
        <ResponsiveCard padding="md">
          <div className="p-6 text-center text-gray-400">
            No trades found
          </div>
        </ResponsiveCard>
      )}
    </div>
  )
}

export default TradesV2
