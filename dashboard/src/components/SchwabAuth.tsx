import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { schwabAuthApi, SchwabAuthInitiate } from '../api/client'
import {
  CheckCircle2,
  XCircle,
  AlertTriangle,
  ExternalLink,
  RefreshCw,
  Trash2,
  Key,
  Clock,
  Copy,
  Check,
} from 'lucide-react'

function SchwabAuth() {
  const queryClient = useQueryClient()
  const [authFlow, setAuthFlow] = useState<SchwabAuthInitiate | null>(null)
  const [callbackUrl, setCallbackUrl] = useState('')
  const [copied, setCopied] = useState(false)

  // Fetch current auth status
  const { data: status, isLoading, error, refetch } = useQuery({
    queryKey: ['schwabAuthStatus'],
    queryFn: () => schwabAuthApi.getStatus().then(res => res.data),
    refetchInterval: 60000, // Refresh every minute
  })

  // Initiate OAuth flow
  const initiateMutation = useMutation({
    mutationFn: () => schwabAuthApi.initiate().then(res => res.data),
    onSuccess: (data) => {
      setAuthFlow(data)
      setCallbackUrl('')
    },
  })

  // Complete OAuth flow with callback
  const callbackMutation = useMutation({
    mutationFn: (url: string) => schwabAuthApi.callback({ callback_url: url }).then(res => res.data),
    onSuccess: () => {
      setAuthFlow(null)
      setCallbackUrl('')
      queryClient.invalidateQueries({ queryKey: ['schwabAuthStatus'] })
    },
  })

  // Delete token
  const deleteMutation = useMutation({
    mutationFn: () => schwabAuthApi.deleteToken().then(res => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['schwabAuthStatus'] })
    },
  })

  const handleCopyUrl = async () => {
    if (authFlow?.authorization_url) {
      await navigator.clipboard.writeText(authFlow.authorization_url)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  const handleSubmitCallback = () => {
    if (callbackUrl.trim()) {
      callbackMutation.mutate(callbackUrl.trim())
    }
  }

  const handleDeleteToken = () => {
    if (window.confirm('Are you sure you want to delete the Schwab token? You will need to re-authenticate.')) {
      deleteMutation.mutate()
    }
  }

  if (isLoading) {
    return (
      <div className="bg-slate-800 rounded-lg p-6 border border-slate-700">
        <div className="flex items-center gap-2 mb-4">
          <Key className="w-5 h-5 text-blue-400" />
          <h3 className="text-lg font-medium">Schwab API Authentication</h3>
        </div>
        <div className="flex items-center justify-center h-24">
          <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-400"></div>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-slate-800 rounded-lg p-6 border border-slate-700">
        <div className="flex items-center gap-2 mb-4">
          <Key className="w-5 h-5 text-blue-400" />
          <h3 className="text-lg font-medium">Schwab API Authentication</h3>
        </div>
        <div className="flex items-center gap-2 text-red-400">
          <XCircle className="w-5 h-5" />
          <span>Failed to load authentication status</span>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-slate-800 rounded-lg p-6 border border-slate-700 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Key className="w-5 h-5 text-blue-400" />
          <h3 className="text-lg font-medium">Schwab API Authentication</h3>
        </div>
        <button
          onClick={() => refetch()}
          className="p-2 hover:bg-slate-700 rounded-lg transition-colors"
          title="Refresh status"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {/* Status Display */}
      <div className="flex items-start gap-4 p-4 bg-slate-700/50 rounded-lg">
        <div className="mt-0.5">
          {status?.authenticated ? (
            <CheckCircle2 className="w-6 h-6 text-green-400" />
          ) : status?.token_exists && !status?.token_valid ? (
            <AlertTriangle className="w-6 h-6 text-yellow-400" />
          ) : (
            <XCircle className="w-6 h-6 text-red-400" />
          )}
        </div>
        <div className="flex-1">
          <div className="font-medium">
            {status?.authenticated
              ? 'Authenticated'
              : status?.token_exists
              ? 'Token Expired'
              : 'Not Authenticated'}
          </div>
          <div className="text-sm text-gray-400 mt-1">{status?.message}</div>

          {status?.token_exists && (
            <div className="flex flex-wrap gap-4 mt-3 text-sm">
              {status.token_age_days !== undefined && (
                <div className="flex items-center gap-1.5 text-gray-400">
                  <Clock className="w-4 h-4" />
                  <span>Age: {status.token_age_days.toFixed(1)} days</span>
                </div>
              )}
              {status.expires_in_days !== undefined && (
                <div className={`flex items-center gap-1.5 ${
                  status.expires_in_days <= 1 ? 'text-red-400' :
                  status.expires_in_days <= 2 ? 'text-yellow-400' : 'text-gray-400'
                }`}>
                  <Clock className="w-4 h-4" />
                  <span>
                    {status.expires_in_days > 0
                      ? `Expires in ${status.expires_in_days.toFixed(1)} days`
                      : 'Expired'}
                  </span>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* OAuth Flow UI */}
      {authFlow ? (
        <div className="space-y-4">
          <div className="p-4 bg-blue-900/30 border border-blue-700 rounded-lg">
            <h4 className="font-medium text-blue-400 mb-2">Complete Authentication</h4>
            <div className="text-sm text-gray-300 space-y-2 whitespace-pre-line">
              {authFlow.instructions}
            </div>
          </div>

          {/* Authorization URL */}
          <div className="space-y-2">
            <label className="block text-sm font-medium text-gray-400">
              Step 1: Open this URL in your browser
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
                className="px-3 py-2 bg-slate-600 hover:bg-slate-500 rounded-lg transition-colors flex items-center gap-2"
              >
                {copied ? (
                  <>
                    <Check className="w-4 h-4 text-green-400" />
                    <span className="text-sm">Copied!</span>
                  </>
                ) : (
                  <>
                    <Copy className="w-4 h-4" />
                    <span className="text-sm">Copy</span>
                  </>
                )}
              </button>
              <a
                href={authFlow.authorization_url}
                target="_blank"
                rel="noopener noreferrer"
                className="px-3 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors flex items-center gap-2"
              >
                <ExternalLink className="w-4 h-4" />
                <span className="text-sm">Open</span>
              </a>
            </div>
          </div>

          {/* Callback URL Input */}
          <div className="space-y-2">
            <label className="block text-sm font-medium text-gray-400">
              Step 2: Paste the redirect URL after login
            </label>
            <textarea
              value={callbackUrl}
              onChange={(e) => setCallbackUrl(e.target.value)}
              placeholder="Paste the full URL from your browser after Schwab redirects you..."
              rows={3}
              className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded-lg text-sm font-mono resize-none"
            />
          </div>

          {/* Submit/Cancel Buttons */}
          <div className="flex gap-3">
            <button
              onClick={handleSubmitCallback}
              disabled={!callbackUrl.trim() || callbackMutation.isPending}
              className="px-4 py-2 bg-green-600 hover:bg-green-700 disabled:bg-green-800 disabled:opacity-50 rounded-lg transition-colors flex items-center gap-2"
            >
              {callbackMutation.isPending ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  <span>Authenticating...</span>
                </>
              ) : (
                <>
                  <CheckCircle2 className="w-4 h-4" />
                  <span>Complete Authentication</span>
                </>
              )}
            </button>
            <button
              onClick={() => setAuthFlow(null)}
              className="px-4 py-2 bg-slate-600 hover:bg-slate-500 rounded-lg transition-colors"
            >
              Cancel
            </button>
          </div>

          {/* Error Display */}
          {callbackMutation.isError && (
            <div className="p-3 bg-red-900/30 border border-red-700 rounded-lg text-red-400 text-sm">
              {(callbackMutation.error as Error)?.message || 'Authentication failed. Please try again.'}
            </div>
          )}
        </div>
      ) : (
        /* Action Buttons */
        <div className="flex gap-3">
          {!status?.authenticated && (
            <button
              onClick={() => initiateMutation.mutate()}
              disabled={initiateMutation.isPending}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded-lg transition-colors flex items-center gap-2"
            >
              {initiateMutation.isPending ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  <span>Starting...</span>
                </>
              ) : (
                <>
                  <Key className="w-4 h-4" />
                  <span>Authenticate with Schwab</span>
                </>
              )}
            </button>
          )}

          {status?.token_exists && (
            <button
              onClick={handleDeleteToken}
              disabled={deleteMutation.isPending}
              className="px-4 py-2 bg-red-600/20 hover:bg-red-600/30 text-red-400 border border-red-600/50 rounded-lg transition-colors flex items-center gap-2"
            >
              {deleteMutation.isPending ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  <span>Deleting...</span>
                </>
              ) : (
                <>
                  <Trash2 className="w-4 h-4" />
                  <span>Delete Token</span>
                </>
              )}
            </button>
          )}
        </div>
      )}

      {/* Initiate Error */}
      {initiateMutation.isError && (
        <div className="p-3 bg-red-900/30 border border-red-700 rounded-lg text-red-400 text-sm">
          {(initiateMutation.error as Error)?.message || 'Failed to start authentication. Check API credentials.'}
        </div>
      )}

      {/* Help Text */}
      <div className="text-sm text-gray-500 border-t border-slate-700 pt-4">
        <p>
          Schwab API tokens expire after 7 days. When the token expires, you'll need to
          re-authenticate by clicking "Authenticate with Schwab" and following the OAuth flow.
        </p>
      </div>
    </div>
  )
}

export default SchwabAuth
