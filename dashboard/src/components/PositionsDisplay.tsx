/**
 * PositionsDisplay Component
 *
 * Responsive positions display that shows:
 * - Card view on mobile (<640px) for touch-friendly interaction
 * - Table view on tablet+ (640px+) for data density
 *
 * @version 1.0.0
 * @part Responsive UI - Phase 3
 */

import clsx from 'clsx'
import { useIsMobileOrSmaller } from '../hooks/useMediaQuery'

interface Position {
  symbol: string
  quantity: number
  avg_cost?: number
  market_value?: number
  unrealized_pnl?: number
  weight_pct?: number
}

interface PositionsDisplayProps {
  positions: Position[]
  className?: string
}

/**
 * Calculate P&L and percentage from position data
 */
function calculatePnL(pos: Position): { pnl: number | null; pnlPct: number | null } {
  const costBasis = pos.avg_cost && pos.quantity ? pos.avg_cost * pos.quantity : null
  const pnl = pos.unrealized_pnl ?? (costBasis && pos.market_value ? pos.market_value - costBasis : null)
  const pnlPct = costBasis && pnl ? (pnl / costBasis) * 100 : null
  return { pnl, pnlPct }
}

/**
 * Format currency value
 */
function formatCurrency(value: number | undefined | null, showCents = true): string {
  if (value === undefined || value === null) return 'N/A'
  return `$${value.toLocaleString(undefined, {
    minimumFractionDigits: showCents ? 2 : 0,
    maximumFractionDigits: showCents ? 2 : 0,
  })}`
}

/**
 * Mobile Card View - Touch-optimized cards for each position
 */
function PositionsCardView({ positions }: { positions: Position[] }) {
  return (
    <div className="space-y-3">
      {positions.map((pos) => {
        const { pnl, pnlPct } = calculatePnL(pos)
        const pnlPositive = (pnl ?? 0) >= 0

        return (
          <div
            key={pos.symbol}
            className="bg-slate-700/50 rounded-lg p-4"
          >
            {/* Header: Symbol + P&L */}
            <div className="flex justify-between items-start mb-3">
              <span className="font-bold text-lg">{pos.symbol}</span>
              <div className="text-right">
                <div
                  className={clsx(
                    'text-lg font-bold',
                    pnlPositive ? 'text-green-400' : 'text-red-400'
                  )}
                >
                  {pnl !== null ? (
                    <>
                      {pnlPositive ? '+' : ''}${pnl.toFixed(2)}
                    </>
                  ) : (
                    'N/A'
                  )}
                </div>
                {pnlPct !== null && (
                  <div
                    className={clsx(
                      'text-xs',
                      pnlPositive ? 'text-green-400/70' : 'text-red-400/70'
                    )}
                  >
                    {pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(1)}%
                  </div>
                )}
              </div>
            </div>

            {/* Details Grid */}
            <div className="grid grid-cols-2 gap-2 text-sm">
              <div>
                <span className="text-gray-400">Qty:</span>
                <span className="ml-2 font-medium">{pos.quantity}</span>
              </div>
              <div>
                <span className="text-gray-400">Weight:</span>
                <span className="ml-2 font-medium">{pos.weight_pct?.toFixed(1)}%</span>
              </div>
              <div>
                <span className="text-gray-400">Avg Cost:</span>
                <span className="ml-2 font-medium">${pos.avg_cost?.toFixed(2) ?? 'N/A'}</span>
              </div>
              <div>
                <span className="text-gray-400">Value:</span>
                <span className="ml-2 font-medium">{formatCurrency(pos.market_value, false)}</span>
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

/**
 * Table View - Dense data display for tablet and desktop
 */
function PositionsTableView({ positions }: { positions: Position[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left">
        <thead className="text-xs sm:text-sm text-gray-400 border-b border-slate-700">
          <tr>
            <th className="pb-3">Symbol</th>
            <th className="pb-3">Quantity</th>
            <th className="pb-3 hidden md:table-cell">Avg Cost</th>
            <th className="pb-3">Market Value</th>
            <th className="pb-3">P&L</th>
            <th className="pb-3 hidden sm:table-cell">Weight</th>
          </tr>
        </thead>
        <tbody className="text-sm sm:text-base">
          {positions.map((pos) => {
            const { pnl, pnlPct } = calculatePnL(pos)
            const pnlPositive = (pnl ?? 0) >= 0

            return (
              <tr key={pos.symbol} className="border-b border-slate-700/50">
                <td className="py-3 font-medium">{pos.symbol}</td>
                <td className="py-3">{pos.quantity}</td>
                <td className="py-3 hidden md:table-cell">
                  ${pos.avg_cost?.toFixed(2) ?? 'N/A'}
                </td>
                <td className="py-3">
                  {formatCurrency(pos.market_value)}
                </td>
                <td
                  className={clsx(
                    'py-3',
                    pnlPositive ? 'text-green-400' : 'text-red-400'
                  )}
                >
                  {pnl !== null ? (
                    <span>
                      ${pnl.toFixed(2)}
                      {pnlPct !== null && (
                        <span className="text-xs ml-1">
                          ({pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(1)}%)
                        </span>
                      )}
                    </span>
                  ) : (
                    'N/A'
                  )}
                </td>
                <td className="py-3 hidden sm:table-cell">
                  {pos.weight_pct?.toFixed(1)}%
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/**
 * PositionsDisplay - Responsive position list
 *
 * Shows card view on mobile for better touch interaction,
 * table view on larger screens for data density.
 */
export function PositionsDisplay({ positions, className }: PositionsDisplayProps) {
  const isMobile = useIsMobileOrSmaller()

  if (!positions || positions.length === 0) {
    return (
      <div className={clsx('text-gray-400 text-sm sm:text-base py-4', className)}>
        No positions
      </div>
    )
  }

  return (
    <div className={className}>
      {isMobile ? (
        <PositionsCardView positions={positions} />
      ) : (
        <PositionsTableView positions={positions} />
      )}
    </div>
  )
}

export default PositionsDisplay
