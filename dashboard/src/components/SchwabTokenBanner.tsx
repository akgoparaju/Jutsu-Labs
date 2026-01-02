import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { schwabAuthApi, SchwabAuthStatus, SchwabAuthInitiate } from '../api/client'

interface TokenBannerProps {
  /** Hide the banner when token is healthy (default: true) */
  hideWhenHealthy?: boolean
  /** Show compact version (default: false) */
  compact?: boolean
}

/**
 * SchwabTokenBanner - Displays token status and provides re-authentication with callback URL input
 * 
 * Shows different banner styles based on token state:
 * - Critical (red): Token expired or <12h remaining
 * - Warning (yellow): Token expiring within 2 days
 * - Info (blue): Token expiring within 5 days
 * - Success (green): Token healthy (>5 days remaining)
 * 
 * Re-authentication Flow:
 * 1. User clicks re-auth button
 * 2. Modal opens with authorization URL
 * 3. User opens URL in new tab, logs in at Schwab
 * 4. Schwab redirects to callback URL
 * 5. User pastes callback URL into modal
 * 6. Click Complete to finish authentication
 */
export function SchwabTokenBanner({ hideWhenHealthy = true, compact = false }: TokenBannerProps) {
  const queryClient = useQueryClient()
  const [showAuthModal, setShowAuthModal] = useState(false)
  const [authFlow, setAuthFlow] = useState<SchwabAuthInitiate | null>(null)
  const [callbackUrl, setCallbackUrl] = useState('')
  const [copied, setCopied] = useState(false)
  const [initError, setInitError] = useState<string | null>(null)

  // Query token status
  const { data: status, isLoading, error } = useQuery({
    queryKey: ['schwab-token-status'],
    queryFn: () => schwabAuthApi.getStatus().then(res => res.data),
    refetchInterval: 60000, // Check every minute
    retry: 1,
  })

  // Initiate OAuth flow mutation
  const initiateMutation = useMutation({
    mutationFn: () => schwabAuthApi.initiate().then(res => res.data),
    onSuccess: (data) => {
      setAuthFlow(data)
      setCallbackUrl('')
      setInitError(null)
    },
    onError: (err: any) => {
      const message = err?.response?.data?.detail || err?.message || 'Failed to start authentication'
      setInitError(message)
    },
  })

  // Complete OAuth flow with callback URL
  const callbackMutation = useMutation({
    mutationFn: (url: string) => schwabAuthApi.callback({ callback_url: url }).then(res => res.data),
    onSuccess: () => {
      // Close modal and reset state
      setShowAuthModal(false)
      setAuthFlow(null)
      setCallbackUrl('')
      setInitError(null)
      // Refresh token status
      queryClient.invalidateQueries({ queryKey: ['schwab-token-status'] })
      queryClient.invalidateQueries({ queryKey: ['schwabAuthStatus'] })
      queryClient.invalidateQueries({ queryKey: ['status'] })
    },
  })

  // Handle re-authentication click - opens modal
  const handleReAuth = () => {
    setShowAuthModal(true)
    setAuthFlow(null)
    setCallbackUrl('')
    setInitError(null)
    // Initiate the OAuth flow
    initiateMutation.mutate()
  }

  // Handle copy URL to clipboard
  const handleCopyUrl = async () => {
    if (authFlow?.authorization_url) {
      await navigator.clipboard.writeText(authFlow.authorization_url)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  // Handle submit callback URL
  const handleSubmitCallback = () => {
    if (callbackUrl.trim()) {
      callbackMutation.mutate(callbackUrl.trim())
    }
  }

  // Handle cancel/close modal
  const handleCloseModal = () => {
    setShowAuthModal(false)
    setAuthFlow(null)
    setCallbackUrl('')
    setInitError(null)
  }

  // Don't show while loading
  if (isLoading) return null

  // Handle error state
  if (error) {
    return (
      <div className="bg-red-900/30 border border-red-600 rounded-lg p-3 mb-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-red-400">⚠️</span>
            <span className="text-red-300 text-sm">Failed to check Schwab token status</span>
          </div>
        </div>
      </div>
    )
  }

  // Determine banner state based on token status
  const getBannerState = (status: SchwabAuthStatus) => {
    if (!status.token_exists) {
      return {
        type: 'critical' as const,
        icon: '🔑',
        title: 'Schwab Not Connected',
        message: 'Connect your Schwab account to enable live trading',
        showButton: true,
        buttonText: 'Connect Schwab',
      }
    }

    if (!status.token_valid) {
      return {
        type: 'critical' as const,
        icon: '🚨',
        title: 'Schwab Token Expired',
        message: 'Your token has expired. Re-authenticate to continue trading.',
        showButton: true,
        buttonText: 'Re-authenticate Now',
      }
    }

    const daysRemaining = status.expires_in_days ?? 7

    if (daysRemaining <= 0.5) {
      // Less than 12 hours
      const hoursRemaining = Math.max(0, daysRemaining * 24)
      return {
        type: 'critical' as const,
        icon: '🚨',
        title: 'Token Expiring Soon!',
        message: `Only ${hoursRemaining.toFixed(0)} hours remaining. Re-authenticate immediately.`,
        showButton: true,
        buttonText: 'Re-authenticate Now',
      }
    }

    if (daysRemaining <= 1) {
      return {
        type: 'critical' as const,
        icon: '⏰',
        title: 'Token Expiring Today',
        message: `Token expires in ${daysRemaining.toFixed(1)} days. Re-authenticate soon.`,
        showButton: true,
        buttonText: 'Re-authenticate',
      }
    }

    if (daysRemaining <= 2) {
      return {
        type: 'warning' as const,
        icon: '⚠️',
        title: 'Token Expiring Soon',
        message: `Token expires in ${daysRemaining.toFixed(1)} days.`,
        showButton: true,
        buttonText: 'Refresh Token',
      }
    }

    if (daysRemaining <= 5) {
      return {
        type: 'info' as const,
        icon: 'ℹ️',
        title: 'Token Status',
        message: `Token expires in ${daysRemaining.toFixed(1)} days.`,
        showButton: true,
        buttonText: 'Refresh Early',
      }
    }

    // Token is healthy
    return {
      type: 'success' as const,
      icon: '✅',
      title: 'Schwab Connected',
      message: `Token valid for ${daysRemaining.toFixed(1)} more days.`,
      showButton: false,
      buttonText: 'Refresh',
    }
  }

  const bannerState = status ? getBannerState(status) : null

  if (!bannerState) return null

  // Hide healthy state if configured
  if (hideWhenHealthy && bannerState.type === 'success') return null

  // Style classes based on banner type
  const styles = {
    critical: {
      container: 'bg-red-900/30 border-red-600',
      text: 'text-red-300',
      title: 'text-red-400',
      button: 'bg-red-600 hover:bg-red-700',
    },
    warning: {
      container: 'bg-yellow-900/30 border-yellow-600',
      text: 'text-yellow-300',
      title: 'text-yellow-400',
      button: 'bg-yellow-600 hover:bg-yellow-700',
    },
    info: {
      container: 'bg-blue-900/30 border-blue-600',
      text: 'text-blue-300',
      title: 'text-blue-400',
      button: 'bg-blue-600 hover:bg-blue-700',
    },
    success: {
      container: 'bg-green-900/30 border-green-600',
      text: 'text-green-300',
      title: 'text-green-400',
      button: 'bg-green-600 hover:bg-green-700',
    },
  }

  const style = styles[bannerState.type]

  // Render auth modal
  const renderAuthModal = () => {
    if (!showAuthModal) return null

    return (
      <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
        <div className="bg-slate-800 rounded-lg border border-slate-700 w-full max-w-xl max-h-[90vh] overflow-y-auto">
          {/* Modal Header */}
          <div className="flex items-center justify-between p-4 border-b border-slate-700">
            <h3 className="text-lg font-semibold">🔑 Schwab Re-Authentication</h3>
            <button
              onClick={handleCloseModal}
              className="text-gray-400 hover:text-white text-xl leading-none"
            >
              ×
            </button>
          </div>

          {/* Modal Body */}
          <div className="p-4 space-y-4">
            {/* Loading state */}
            {initiateMutation.isPending && (
              <div className="flex items-center justify-center py-8">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-400"></div>
                <span className="ml-3 text-gray-400">Starting authentication...</span>
              </div>
            )}

            {/* Init error */}
            {initError && (
              <div className="p-3 bg-red-900/30 border border-red-700 rounded-lg text-red-400 text-sm">
                {initError}
              </div>
            )}

            {/* Auth flow UI */}
            {authFlow && (
              <>
                {/* Instructions */}
                <div className="p-3 bg-blue-900/30 border border-blue-700 rounded-lg">
                  <h4 className="font-medium text-blue-400 mb-2">Instructions</h4>
                  <ol className="text-sm text-gray-300 space-y-1 list-decimal list-inside">
                    <li>Click "Open Schwab" to login at Schwab</li>
                    <li>After login, you'll be redirected to a URL starting with <code className="text-xs bg-slate-700 px-1 rounded">https://127.0.0.1</code></li>
                    <li>Copy that <strong>entire URL</strong> from your browser</li>
                    <li>Paste it below and click "Complete Authentication"</li>
                  </ol>
                </div>

                {/* Step 1: Authorization URL */}
                <div className="space-y-2">
                  <label className="block text-sm font-medium text-gray-400">
                    Step 1: Open Schwab Login
                  </label>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={authFlow.authorization_url}
                      readOnly
                      className="flex-1 px-3 py-2 bg-slate-700 border border-slate-600 rounded-lg text-sm font-mono truncate"
                    />
                    <button
                      onClick={handleCopyUrl}
                      className="px-3 py-2 bg-slate-600 hover:bg-slate-500 rounded-lg transition-colors text-sm"
                    >
                      {copied ? '✓ Copied' : '📋 Copy'}
                    </button>
                    <a
                      href={authFlow.authorization_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="px-3 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors text-sm font-medium"
                    >
                      🔗 Open Schwab
                    </a>
                  </div>
                </div>

                {/* Step 2: Callback URL Input */}
                <div className="space-y-2">
                  <label className="block text-sm font-medium text-gray-400">
                    Step 2: Paste Redirect URL
                  </label>
                  <textarea
                    value={callbackUrl}
                    onChange={(e) => setCallbackUrl(e.target.value)}
                    placeholder="Paste the full URL from your browser after Schwab redirects you...

Example: https://127.0.0.1:8182/?code=C0.b2F1dGgy...&session=..."
                    rows={4}
                    className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded-lg text-sm font-mono resize-none"
                  />
                </div>

                {/* Callback error */}
                {callbackMutation.isError && (
                  <div className="p-3 bg-red-900/30 border border-red-700 rounded-lg text-red-400 text-sm">
                    {(() => {
                      const err = callbackMutation.error as any
                      return err?.response?.data?.detail || err?.message || 'Authentication failed. Please try again.'
                    })()}
                  </div>
                )}

                {/* Action Buttons */}
                <div className="flex gap-3 pt-2">
                  <button
                    onClick={handleSubmitCallback}
                    disabled={!callbackUrl.trim() || callbackMutation.isPending}
                    className="flex-1 px-4 py-2 bg-green-600 hover:bg-green-700 disabled:bg-green-800 disabled:opacity-50 rounded-lg transition-colors font-medium"
                  >
                    {callbackMutation.isPending ? (
                      <span className="flex items-center justify-center gap-2">
                        <span className="animate-spin">⏳</span>
                        Authenticating...
                      </span>
                    ) : (
                      '✓ Complete Authentication'
                    )}
                  </button>
                  <button
                    onClick={handleCloseModal}
                    className="px-4 py-2 bg-slate-600 hover:bg-slate-500 rounded-lg transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    )
  }

  if (compact) {
    return (
      <>
        {renderAuthModal()}
        <div className={`${style.container} border rounded-lg p-2 mb-4`}>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span>{bannerState.icon}</span>
              <span className={`${style.text} text-sm`}>{bannerState.message}</span>
            </div>
            {bannerState.showButton && (
              <button
                onClick={handleReAuth}
                disabled={initiateMutation.isPending}
                className={`${style.button} px-3 py-1 rounded text-sm font-medium text-white transition-colors disabled:opacity-50`}
              >
                {bannerState.buttonText}
              </button>
            )}
          </div>
        </div>
      </>
    )
  }

  return (
    <>
      {renderAuthModal()}
      <div className={`${style.container} border rounded-lg p-4 mb-4`}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-2xl">{bannerState.icon}</span>
            <div>
              <h4 className={`${style.title} font-semibold`}>{bannerState.title}</h4>
              <p className={`${style.text} text-sm`}>{bannerState.message}</p>
            </div>
          </div>
          {bannerState.showButton && (
            <button
              onClick={handleReAuth}
              disabled={initiateMutation.isPending}
              className={`${style.button} px-4 py-2 rounded-lg font-medium text-white transition-colors disabled:opacity-50`}
            >
              {bannerState.buttonText}
            </button>
          )}
        </div>
      </div>
    </>
  )
}

export default SchwabTokenBanner
