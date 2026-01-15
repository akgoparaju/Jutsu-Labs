import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { tradesApi, TradeRecord } from '../../api/client'
import { ExecuteTradeModal } from '../../components/ExecuteTradeModal'

function Trades() {
  const queryClient = useQueryClient()
  const [page, setPage] = useState(1)
  const [pageSize] = useState(20)
  const [filters, setFilters] = useState({
    symbol: '',
    mode: '',
    action: '',
  })
  const [showTradeModal, setShowTradeModal] = useState(false)

  const handleTradeSuccess = () => {
    // Refresh trades data after successful trade
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
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">Trade History</h2>
        <div className="flex gap-3">
          <button
            onClick={() => setShowTradeModal(true)}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors font-medium"
          >
            Execute Trade
          </button>
          <button
            onClick={handleExport}
            className="px-4 py-2 bg-green-600 hover:bg-green-700 rounded-lg transition-colors"
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
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
            <div className="text-sm text-gray-400 mb-1">Total Trades</div>
            <div className="text-2xl font-bold">{stats.total_trades ?? 0}</div>
          </div>
          <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
            <div className="text-sm text-gray-400 mb-1">Win Rate</div>
            <div className="text-2xl font-bold text-green-400">
              {((stats.win_rate ?? 0) * 100).toFixed(1)}%
            </div>
          </div>
          <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
            <div className="text-sm text-gray-400 mb-1">Avg Slippage</div>
            <div className="text-2xl font-bold text-yellow-400">
              {(stats.avg_slippage_pct ?? 0).toFixed(3)}%
            </div>
          </div>
          <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
            <div className="text-sm text-gray-400 mb-1">Total Volume</div>
            <div className="text-2xl font-bold">
              ${(stats.total_volume ?? 0).toLocaleString()}
            </div>
          </div>
          <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
            <div className="text-sm text-gray-400 mb-1">Net P&L</div>
            <div className={`text-2xl font-bold ${
              (stats.net_pnl ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'
            }`}>
              ${(stats.net_pnl ?? 0).toLocaleString()}
            </div>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
        <div className="flex flex-wrap gap-4">
          <div>
            <label className="block text-sm text-gray-400 mb-1">Symbol</label>
            <input
              type="text"
              value={filters.symbol}
              onChange={(e) => setFilters({ ...filters, symbol: e.target.value })}
              placeholder="e.g., QQQ"
              className="px-3 py-2 bg-slate-700 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm text-gray-400 mb-1">Mode</label>
            <select
              value={filters.mode}
              onChange={(e) => setFilters({ ...filters, mode: e.target.value })}
              className="px-3 py-2 bg-slate-700 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500"
            >
              <option value="">All Modes</option>
              <option value="offline_mock">Offline Mock</option>
              <option value="online_mock">Online Mock</option>
              <option value="online_live">Online Live</option>
            </select>
          </div>
          <div>
            <label className="block text-sm text-gray-400 mb-1">Action</label>
            <select
              value={filters.action}
              onChange={(e) => setFilters({ ...filters, action: e.target.value })}
              className="px-3 py-2 bg-slate-700 rounded-lg border border-slate-600 focus:outline-none focus:border-blue-500"
            >
              <option value="">All Actions</option>
              <option value="BUY">Buy</option>
              <option value="SELL">Sell</option>
            </select>
          </div>
          <div className="flex items-end">
            <button
              onClick={() => setFilters({ symbol: '', mode: '', action: '' })}
              className="px-3 py-2 bg-slate-600 hover:bg-slate-500 rounded-lg transition-colors"
            >
              Clear Filters
            </button>
          </div>
        </div>
      </div>

      {/* Trades Table */}
      <div className="bg-slate-800 rounded-lg border border-slate-700 overflow-hidden">
        {isLoading ? (
          <div className="flex items-center justify-center h-64">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-400"></div>
          </div>
        ) : error ? (
          <div className="p-6 text-center text-red-400">
            Failed to load trades
          </div>
        ) : data?.trades && data.trades.length > 0 ? (
          <>
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

            {/* Pagination */}
            <div className="flex items-center justify-between px-4 py-3 bg-slate-700/30">
              <div className="text-sm text-gray-400">
                Showing {((page - 1) * pageSize) + 1} to {Math.min(page * pageSize, data.total)} of {data.total} trades
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="px-3 py-1 bg-slate-600 hover:bg-slate-500 rounded disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Previous
                </button>
                <span className="px-3 py-1 bg-slate-700 rounded">
                  Page {page} of {data.total_pages}
                </span>
                <button
                  onClick={() => setPage(p => Math.min(data.total_pages, p + 1))}
                  disabled={page >= data.total_pages}
                  className="px-3 py-1 bg-slate-600 hover:bg-slate-500 rounded disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Next
                </button>
              </div>
            </div>
          </>
        ) : (
          <div className="p-6 text-center text-gray-400">
            No trades found
          </div>
        )}
      </div>
    </div>
  )
}

export default Trades
