import { useState } from 'react'
import { tradesApi, ExecuteTradeRequest, ExecuteTradeResponse } from '../api/client'

// Valid symbols for trading
const VALID_SYMBOLS = ['QQQ', 'TQQQ', 'PSQ', 'TMF', 'TMV', 'TLT'] as const

interface ExecuteTradeModalProps {
  isOpen: boolean
  onClose: () => void
  onSuccess?: (trade: ExecuteTradeResponse) => void
  defaultSymbol?: string
  defaultAction?: 'BUY' | 'SELL'
}

type Step = 'input' | 'confirm' | 'loading' | 'result'

export function ExecuteTradeModal({
  isOpen,
  onClose,
  onSuccess,
  defaultSymbol,
  defaultAction,
}: ExecuteTradeModalProps) {
  // Form state
  const [symbol, setSymbol] = useState(defaultSymbol || 'QQQ')
  const [action, setAction] = useState<'BUY' | 'SELL'>(defaultAction || 'BUY')
  const [quantity, setQuantity] = useState('')
  const [reason, setReason] = useState('')

  // UI state
  const [step, setStep] = useState<Step>('input')
  const [result, setResult] = useState<ExecuteTradeResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Reset form
  const resetForm = () => {
    setSymbol(defaultSymbol || 'QQQ')
    setAction(defaultAction || 'BUY')
    setQuantity('')
    setReason('')
    setStep('input')
    setResult(null)
    setError(null)
  }

  // Handle close
  const handleClose = () => {
    resetForm()
    onClose()
  }

  // Validate form
  const isValid = () => {
    const qty = parseInt(quantity)
    return symbol && action && qty > 0 && qty <= 10000
  }

  // Handle confirm step
  const handleConfirm = () => {
    if (!isValid()) return
    setStep('confirm')
  }

  // Handle execute
  const handleExecute = async () => {
    setStep('loading')
    setError(null)

    try {
      const request: ExecuteTradeRequest = {
        symbol,
        action,
        quantity: parseInt(quantity),
        reason: reason || undefined,
      }

      const response = await tradesApi.executeTrade(request)
      setResult(response.data)
      setStep('result')

      if (response.data.success) {
        onSuccess?.(response.data)
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Failed to execute trade')
      setStep('result')
    }
  }

  // Handle back
  const handleBack = () => {
    if (step === 'confirm') {
      setStep('input')
    } else if (step === 'result') {
      resetForm()
    }
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black bg-opacity-50"
        onClick={handleClose}
      />

      {/* Modal */}
      <div className="relative bg-white rounded-lg shadow-xl w-full max-w-md mx-4 p-6">
        {/* Header */}
        <div className="flex justify-between items-center mb-6">
          <h2 className="text-xl font-bold text-gray-900">
            {step === 'result' && result?.success
              ? 'Trade Executed'
              : step === 'result' && error
              ? 'Execution Failed'
              : 'Execute Trade'}
          </h2>
          <button
            onClick={handleClose}
            className="text-gray-400 hover:text-gray-600"
          >
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Content based on step */}
        {step === 'input' && (
          <div className="space-y-4">
            {/* Symbol Select */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Symbol
              </label>
              <select
                value={symbol}
                onChange={(e) => setSymbol(e.target.value)}
                className="w-full border border-gray-300 rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                {VALID_SYMBOLS.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>

            {/* Action Toggle */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Action
              </label>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setAction('BUY')}
                  className={`flex-1 py-2 px-4 rounded-md font-medium transition-colors ${
                    action === 'BUY'
                      ? 'bg-green-600 text-white'
                      : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                  }`}
                >
                  BUY
                </button>
                <button
                  type="button"
                  onClick={() => setAction('SELL')}
                  className={`flex-1 py-2 px-4 rounded-md font-medium transition-colors ${
                    action === 'SELL'
                      ? 'bg-red-600 text-white'
                      : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                  }`}
                >
                  SELL
                </button>
              </div>
            </div>

            {/* Quantity Input */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Quantity (Shares)
              </label>
              <input
                type="number"
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
                placeholder="Enter number of shares"
                min="1"
                max="10000"
                className="w-full border border-gray-300 rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              {quantity && parseInt(quantity) > 10000 && (
                <p className="text-red-500 text-sm mt-1">Maximum 10,000 shares</p>
              )}
            </div>

            {/* Reason (Optional) */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Reason (Optional)
              </label>
              <input
                type="text"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="e.g., Manual rebalance"
                className="w-full border border-gray-300 rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>

            {/* Submit Button */}
            <button
              onClick={handleConfirm}
              disabled={!isValid()}
              className={`w-full py-3 px-4 rounded-md font-medium transition-colors ${
                isValid()
                  ? 'bg-blue-600 text-white hover:bg-blue-700'
                  : 'bg-gray-300 text-gray-500 cursor-not-allowed'
              }`}
            >
              Review Trade
            </button>
          </div>
        )}

        {step === 'confirm' && (
          <div className="space-y-4">
            {/* Trade Summary */}
            <div className="bg-gray-50 rounded-lg p-4 space-y-3">
              <div className="flex justify-between">
                <span className="text-gray-600">Symbol:</span>
                <span className="font-medium">{symbol}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Action:</span>
                <span className={`font-medium ${action === 'BUY' ? 'text-green-600' : 'text-red-600'}`}>
                  {action}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Quantity:</span>
                <span className="font-medium">{parseInt(quantity).toLocaleString()} shares</span>
              </div>
              {reason && (
                <div className="flex justify-between">
                  <span className="text-gray-600">Reason:</span>
                  <span className="font-medium text-right max-w-[60%] truncate">{reason}</span>
                </div>
              )}
            </div>

            {/* Warning */}
            <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3">
              <p className="text-yellow-800 text-sm">
                <strong>Confirm:</strong> This will execute a {action.toLowerCase()} order for {parseInt(quantity).toLocaleString()} shares of {symbol}.
              </p>
            </div>

            {/* Action Buttons */}
            <div className="flex gap-3">
              <button
                onClick={handleBack}
                className="flex-1 py-3 px-4 rounded-md font-medium bg-gray-100 text-gray-700 hover:bg-gray-200 transition-colors"
              >
                Back
              </button>
              <button
                onClick={handleExecute}
                className={`flex-1 py-3 px-4 rounded-md font-medium transition-colors ${
                  action === 'BUY'
                    ? 'bg-green-600 text-white hover:bg-green-700'
                    : 'bg-red-600 text-white hover:bg-red-700'
                }`}
              >
                Execute {action}
              </button>
            </div>
          </div>
        )}

        {step === 'loading' && (
          <div className="py-8 text-center">
            <div className="inline-block animate-spin rounded-full h-12 w-12 border-4 border-blue-600 border-t-transparent"></div>
            <p className="mt-4 text-gray-600">Executing trade...</p>
          </div>
        )}

        {step === 'result' && (
          <div className="space-y-4">
            {result?.success ? (
              <>
                {/* Success */}
                <div className="text-center">
                  <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-green-100 mb-4">
                    <svg className="w-8 h-8 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                  </div>
                  <h3 className="text-lg font-medium text-gray-900">{result.message}</h3>
                </div>

                {/* Trade Details */}
                <div className="bg-gray-50 rounded-lg p-4 space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-gray-600">Trade ID:</span>
                    <span className="font-medium">#{result.trade_id}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-600">Fill Price:</span>
                    <span className="font-medium">${result.fill_price?.toFixed(2)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-600">Total Value:</span>
                    <span className="font-medium">${result.fill_value?.toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-600">Slippage:</span>
                    <span className="font-medium">{(result.slippage_pct || 0).toFixed(3)}%</span>
                  </div>
                </div>
              </>
            ) : (
              <>
                {/* Error */}
                <div className="text-center">
                  <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-red-100 mb-4">
                    <svg className="w-8 h-8 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </div>
                  <h3 className="text-lg font-medium text-gray-900">Execution Failed</h3>
                  <p className="text-red-600 mt-2">{error || result?.message}</p>
                </div>
              </>
            )}

            {/* Close/Retry Button */}
            <div className="flex gap-3">
              {!result?.success && (
                <button
                  onClick={handleBack}
                  className="flex-1 py-3 px-4 rounded-md font-medium bg-gray-100 text-gray-700 hover:bg-gray-200 transition-colors"
                >
                  Try Again
                </button>
              )}
              <button
                onClick={handleClose}
                className="flex-1 py-3 px-4 rounded-md font-medium bg-blue-600 text-white hover:bg-blue-700 transition-colors"
              >
                {result?.success ? 'Done' : 'Close'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default ExecuteTradeModal
