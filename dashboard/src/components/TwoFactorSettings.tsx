import { useState, useEffect } from 'react'
import { Shield, ShieldCheck, ShieldOff, Copy, Check, AlertTriangle, Key, RefreshCw, Eye, EyeOff } from 'lucide-react'
import { getAuthHeaders } from '../contexts/AuthContext'

// API base URL from environment or default
const API_BASE = (import.meta as any).env?.VITE_API_URL || 'http://localhost:8000'

interface TwoFactorStatus {
  enabled: boolean
  available: boolean
  message: string
}

interface SetupResponse {
  secret: string
  qr_code: string | null
  provisioning_uri: string
  message: string
}

interface VerifyResponse {
  success: boolean
  backup_codes: string[] | null
  message: string
}

type ViewState = 'loading' | 'not_enabled' | 'setup' | 'verify' | 'enabled' | 'backup_codes' | 'disable'

function TwoFactorSettings() {
  const [viewState, setViewState] = useState<ViewState>('loading')
  const [status, setStatus] = useState<TwoFactorStatus | null>(null)
  const [setupData, setSetupData] = useState<SetupResponse | null>(null)
  const [backupCodes, setBackupCodes] = useState<string[]>([])
  const [verifyCode, setVerifyCode] = useState('')
  const [disablePassword, setDisablePassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [copiedSecret, setCopiedSecret] = useState(false)
  const [copiedCodes, setCopiedCodes] = useState(false)

  // Fetch 2FA status on mount
  useEffect(() => {
    fetchStatus()
  }, [])

  const fetchStatus = async () => {
    try {
      setViewState('loading')
      setError(null)
      const response = await fetch(`${API_BASE}/api/2fa/status`, {
        headers: getAuthHeaders()
      })
      if (response.ok) {
        const data: TwoFactorStatus = await response.json()
        setStatus(data)
        setViewState(data.enabled ? 'enabled' : 'not_enabled')
      } else {
        setError('Failed to fetch 2FA status')
        setViewState('not_enabled')
      }
    } catch (err) {
      setError('Failed to connect to server')
      setViewState('not_enabled')
    }
  }

  const startSetup = async () => {
    try {
      setIsSubmitting(true)
      setError(null)
      const response = await fetch(`${API_BASE}/api/2fa/setup`, {
        method: 'POST',
        headers: getAuthHeaders()
      })
      if (response.ok) {
        const data: SetupResponse = await response.json()
        setSetupData(data)
        setViewState('setup')
      } else {
        const errorData = await response.json()
        setError(errorData.detail || 'Failed to start 2FA setup')
      }
    } catch (err) {
      setError('Failed to connect to server')
    } finally {
      setIsSubmitting(false)
    }
  }

  const verifyAndEnable = async () => {
    if (!verifyCode || verifyCode.length !== 6) {
      setError('Please enter a 6-digit code')
      return
    }

    try {
      setIsSubmitting(true)
      setError(null)
      const response = await fetch(`${API_BASE}/api/2fa/verify`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({ code: verifyCode })
      })
      if (response.ok) {
        const data: VerifyResponse = await response.json()
        if (data.success && data.backup_codes) {
          setBackupCodes(data.backup_codes)
          setViewState('backup_codes')
        }
      } else {
        const errorData = await response.json()
        setError(errorData.detail || 'Invalid verification code')
      }
    } catch (err) {
      setError('Failed to connect to server')
    } finally {
      setIsSubmitting(false)
    }
  }

  const disableTwoFactor = async () => {
    if (!disablePassword) {
      setError('Please enter your password')
      return
    }

    try {
      setIsSubmitting(true)
      setError(null)
      const response = await fetch(`${API_BASE}/api/2fa/disable`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({ password: disablePassword })
      })
      if (response.ok) {
        setDisablePassword('')
        setViewState('not_enabled')
        setStatus({ ...status!, enabled: false })
      } else {
        const errorData = await response.json()
        setError(errorData.detail || 'Failed to disable 2FA')
      }
    } catch (err) {
      setError('Failed to connect to server')
    } finally {
      setIsSubmitting(false)
    }
  }

  const regenerateBackupCodes = async () => {
    try {
      setIsSubmitting(true)
      setError(null)
      const response = await fetch(`${API_BASE}/api/2fa/backup-codes`, {
        method: 'POST',
        headers: getAuthHeaders()
      })
      if (response.ok) {
        const data = await response.json()
        setBackupCodes(data.backup_codes)
        setViewState('backup_codes')
      } else {
        const errorData = await response.json()
        setError(errorData.detail || 'Failed to regenerate backup codes')
      }
    } catch (err) {
      setError('Failed to connect to server')
    } finally {
      setIsSubmitting(false)
    }
  }

  const copyToClipboard = async (text: string, type: 'secret' | 'codes') => {
    try {
      await navigator.clipboard.writeText(text)
      if (type === 'secret') {
        setCopiedSecret(true)
        setTimeout(() => setCopiedSecret(false), 2000)
      } else {
        setCopiedCodes(true)
        setTimeout(() => setCopiedCodes(false), 2000)
      }
    } catch (err) {
      console.error('Failed to copy:', err)
    }
  }

  const finishSetup = () => {
    setViewState('enabled')
    setSetupData(null)
    setVerifyCode('')
    setBackupCodes([])
    fetchStatus()
  }

  // Loading state
  if (viewState === 'loading') {
    return (
      <div className="bg-slate-800 rounded-lg p-6">
        <div className="flex items-center gap-3">
          <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-blue-500"></div>
          <span className="text-gray-400">Loading 2FA settings...</span>
        </div>
      </div>
    )
  }

  // Not enabled - show enable button
  if (viewState === 'not_enabled') {
    return (
      <div className="bg-slate-800 rounded-lg p-6">
        <div className="flex items-start gap-4">
          <div className="p-3 bg-slate-700 rounded-lg">
            <ShieldOff className="w-6 h-6 text-gray-400" />
          </div>
          <div className="flex-1">
            <h3 className="text-lg font-semibold text-white mb-1">Two-Factor Authentication</h3>
            <p className="text-gray-400 text-sm mb-4">
              Add an extra layer of security to your account by requiring a verification code from your authenticator app.
            </p>
            
            {error && (
              <div className="bg-red-500/10 border border-red-500/50 rounded-lg p-3 mb-4">
                <p className="text-red-400 text-sm">{error}</p>
              </div>
            )}

            {status && !status.available && (
              <div className="bg-yellow-500/10 border border-yellow-500/50 rounded-lg p-3 mb-4">
                <p className="text-yellow-400 text-sm">
                  2FA is not available on the server. Please install: pip install pyotp qrcode[pil]
                </p>
              </div>
            )}

            <button
              onClick={startSetup}
              disabled={isSubmitting || !!(status && !status.available)}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-lg transition-colors flex items-center gap-2"
            >
              {isSubmitting ? (
                <>
                  <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                  Setting up...
                </>
              ) : (
                <>
                  <Shield className="w-4 h-4" />
                  Enable 2FA
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    )
  }

  // Setup - show QR code and verification
  if (viewState === 'setup' && setupData) {
    return (
      <div className="bg-slate-800 rounded-lg p-6">
        <div className="flex items-start gap-4">
          <div className="p-3 bg-blue-600/20 rounded-lg">
            <Shield className="w-6 h-6 text-blue-400" />
          </div>
          <div className="flex-1">
            <h3 className="text-lg font-semibold text-white mb-1">Set Up Two-Factor Authentication</h3>
            <p className="text-gray-400 text-sm mb-6">
              Scan the QR code with your authenticator app (Google Authenticator, Authy, etc.)
            </p>

            {error && (
              <div className="bg-red-500/10 border border-red-500/50 rounded-lg p-3 mb-4">
                <p className="text-red-400 text-sm">{error}</p>
              </div>
            )}

            <div className="grid md:grid-cols-2 gap-6">
              {/* QR Code */}
              <div className="flex flex-col items-center">
                {setupData.qr_code ? (
                  <img 
                    src={setupData.qr_code} 
                    alt="2FA QR Code" 
                    className="w-48 h-48 bg-white p-2 rounded-lg"
                  />
                ) : (
                  <div className="w-48 h-48 bg-gray-700 rounded-lg flex items-center justify-center">
                    <p className="text-gray-400 text-sm text-center p-4">
                      QR code not available. Use manual entry below.
                    </p>
                  </div>
                )}
                <p className="text-gray-500 text-xs mt-2">Scan with authenticator app</p>
              </div>

              {/* Manual entry and verification */}
              <div className="space-y-4">
                {/* Manual secret */}
                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-2">
                    Or enter this code manually:
                  </label>
                  <div className="flex items-center gap-2">
                    <code className="flex-1 px-3 py-2 bg-gray-700 rounded-lg text-green-400 font-mono text-sm break-all">
                      {setupData.secret}
                    </code>
                    <button
                      onClick={() => copyToClipboard(setupData.secret, 'secret')}
                      className="p-2 text-gray-400 hover:text-white transition-colors"
                      title="Copy secret"
                    >
                      {copiedSecret ? <Check className="w-4 h-4 text-green-400" /> : <Copy className="w-4 h-4" />}
                    </button>
                  </div>
                </div>

                {/* Verification code input */}
                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-2">
                    Enter verification code:
                  </label>
                  <input
                    type="text"
                    value={verifyCode}
                    onChange={(e) => setVerifyCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                    placeholder="000000"
                    className="w-full px-4 py-3 bg-gray-700 border border-gray-600 rounded-lg text-white text-center text-2xl font-mono tracking-widest placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
                    maxLength={6}
                  />
                </div>

                <div className="flex gap-3">
                  <button
                    onClick={() => {
                      setViewState('not_enabled')
                      setSetupData(null)
                      setVerifyCode('')
                      setError(null)
                    }}
                    className="px-4 py-2 bg-gray-600 hover:bg-gray-500 text-white rounded-lg transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={verifyAndEnable}
                    disabled={isSubmitting || verifyCode.length !== 6}
                    className="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-lg transition-colors flex items-center justify-center gap-2"
                  >
                    {isSubmitting ? (
                      <>
                        <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                        Verifying...
                      </>
                    ) : (
                      'Verify & Enable'
                    )}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    )
  }

  // Show backup codes after enabling
  if (viewState === 'backup_codes' && backupCodes.length > 0) {
    return (
      <div className="bg-slate-800 rounded-lg p-6">
        <div className="flex items-start gap-4">
          <div className="p-3 bg-green-600/20 rounded-lg">
            <ShieldCheck className="w-6 h-6 text-green-400" />
          </div>
          <div className="flex-1">
            <h3 className="text-lg font-semibold text-white mb-1">Save Your Backup Codes</h3>
            <p className="text-gray-400 text-sm mb-4">
              Store these codes securely. Each code can only be used once to access your account if you lose access to your authenticator.
            </p>

            <div className="bg-yellow-500/10 border border-yellow-500/50 rounded-lg p-3 mb-4 flex items-start gap-2">
              <AlertTriangle className="w-5 h-5 text-yellow-400 flex-shrink-0 mt-0.5" />
              <p className="text-yellow-400 text-sm">
                These codes will only be shown once. Make sure to save them now!
              </p>
            </div>

            <div className="bg-gray-700 rounded-lg p-4 mb-4">
              <div className="flex justify-between items-center mb-3">
                <span className="text-sm font-medium text-gray-300">Backup Codes</span>
                <button
                  onClick={() => copyToClipboard(backupCodes.join('\n'), 'codes')}
                  className="text-sm text-blue-400 hover:text-blue-300 flex items-center gap-1"
                >
                  {copiedCodes ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                  {copiedCodes ? 'Copied!' : 'Copy all'}
                </button>
              </div>
              <div className="grid grid-cols-2 gap-2">
                {backupCodes.map((code, index) => (
                  <code key={index} className="px-3 py-2 bg-gray-800 rounded text-green-400 font-mono text-sm text-center">
                    {code}
                  </code>
                ))}
              </div>
            </div>

            <button
              onClick={finishSetup}
              className="w-full px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg transition-colors"
            >
              I've Saved My Backup Codes
            </button>
          </div>
        </div>
      </div>
    )
  }

  // Enabled state - show status and options
  if (viewState === 'enabled') {
    return (
      <div className="bg-slate-800 rounded-lg p-6">
        <div className="flex items-start gap-4">
          <div className="p-3 bg-green-600/20 rounded-lg">
            <ShieldCheck className="w-6 h-6 text-green-400" />
          </div>
          <div className="flex-1">
            <h3 className="text-lg font-semibold text-white mb-1">Two-Factor Authentication</h3>
            <p className="text-green-400 text-sm mb-4 flex items-center gap-2">
              <ShieldCheck className="w-4 h-4" />
              2FA is enabled for your account
            </p>

            {error && (
              <div className="bg-red-500/10 border border-red-500/50 rounded-lg p-3 mb-4">
                <p className="text-red-400 text-sm">{error}</p>
              </div>
            )}

            <div className="space-y-3">
              {/* Regenerate backup codes */}
              <button
                onClick={regenerateBackupCodes}
                disabled={isSubmitting}
                className="w-full px-4 py-3 bg-slate-700 hover:bg-slate-600 text-white rounded-lg transition-colors flex items-center gap-3"
              >
                <Key className="w-5 h-5 text-gray-400" />
                <div className="text-left">
                  <div className="font-medium">Generate New Backup Codes</div>
                  <div className="text-sm text-gray-400">Invalidates previous codes</div>
                </div>
                <RefreshCw className={`w-4 h-4 ml-auto ${isSubmitting ? 'animate-spin' : ''}`} />
              </button>

              {/* Disable 2FA */}
              <button
                onClick={() => {
                  setViewState('disable')
                  setError(null)
                }}
                className="w-full px-4 py-3 bg-red-600/20 hover:bg-red-600/30 text-red-400 rounded-lg transition-colors flex items-center gap-3"
              >
                <ShieldOff className="w-5 h-5" />
                <div className="text-left">
                  <div className="font-medium">Disable 2FA</div>
                  <div className="text-sm text-red-400/70">Requires password confirmation</div>
                </div>
              </button>
            </div>
          </div>
        </div>
      </div>
    )
  }

  // Disable confirmation
  if (viewState === 'disable') {
    return (
      <div className="bg-slate-800 rounded-lg p-6">
        <div className="flex items-start gap-4">
          <div className="p-3 bg-red-600/20 rounded-lg">
            <AlertTriangle className="w-6 h-6 text-red-400" />
          </div>
          <div className="flex-1">
            <h3 className="text-lg font-semibold text-white mb-1">Disable Two-Factor Authentication</h3>
            <p className="text-gray-400 text-sm mb-4">
              Enter your password to confirm disabling 2FA. This will make your account less secure.
            </p>

            {error && (
              <div className="bg-red-500/10 border border-red-500/50 rounded-lg p-3 mb-4">
                <p className="text-red-400 text-sm">{error}</p>
              </div>
            )}

            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-300 mb-2">
                Confirm Password
              </label>
              <div className="relative">
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={disablePassword}
                  onChange={(e) => setDisablePassword(e.target.value)}
                  placeholder="Enter your password"
                  className="w-full px-4 py-3 pr-12 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-red-500"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-white"
                >
                  {showPassword ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
                </button>
              </div>
            </div>

            <div className="flex gap-3">
              <button
                onClick={() => {
                  setViewState('enabled')
                  setDisablePassword('')
                  setError(null)
                }}
                className="px-4 py-2 bg-gray-600 hover:bg-gray-500 text-white rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={disableTwoFactor}
                disabled={isSubmitting || !disablePassword}
                className="flex-1 px-4 py-2 bg-red-600 hover:bg-red-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-lg transition-colors flex items-center justify-center gap-2"
              >
                {isSubmitting ? (
                  <>
                    <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                    Disabling...
                  </>
                ) : (
                  'Disable 2FA'
                )}
              </button>
            </div>
          </div>
        </div>
      </div>
    )
  }

  return null
}

export default TwoFactorSettings
