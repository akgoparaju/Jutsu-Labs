import { useState, useEffect } from 'react'
import { Key, Fingerprint, Smartphone, Laptop, Trash2, Plus, AlertTriangle, Shield } from 'lucide-react'
import { getAuthHeaders } from '../contexts/AuthContext'

// API base URL from environment or empty for same-origin requests (required for Docker)
const API_BASE = (import.meta as any).env?.VITE_API_URL || ''

interface PasskeyStatus {
  available: boolean
  count: number
  message: string
}

interface PasskeyInfo {
  id: number
  device_name: string | null
  created_at: string
  last_used_at: string | null
}

interface PasskeyListResponse {
  passkeys: PasskeyInfo[]
  count: number
}

type ViewState = 'loading' | 'list' | 'register' | 'error'

// Check if WebAuthn is supported in this browser
const isWebAuthnSupported = (): boolean => {
  return window.PublicKeyCredential !== undefined
}

// Base64URL encoding/decoding helpers for WebAuthn
const base64UrlToArrayBuffer = (base64url: string): ArrayBuffer => {
  const base64 = base64url.replace(/-/g, '+').replace(/_/g, '/')
  const padding = '='.repeat((4 - (base64.length % 4)) % 4)
  const binary = atob(base64 + padding)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i)
  }
  return bytes.buffer
}

const arrayBufferToBase64Url = (buffer: ArrayBuffer): string => {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i])
  }
  const base64 = btoa(binary)
  return base64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '')
}

function PasskeySettings() {
  const [viewState, setViewState] = useState<ViewState>('loading')
  const [status, setStatus] = useState<PasskeyStatus | null>(null)
  const [passkeys, setPasskeys] = useState<PasskeyInfo[]>([])
  const [deviceName, setDeviceName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [browserSupported, setBrowserSupported] = useState(true)

  // Check browser support on mount
  useEffect(() => {
    setBrowserSupported(isWebAuthnSupported())
    fetchStatus()
  }, [])

  const fetchStatus = async () => {
    try {
      setViewState('loading')
      setError(null)

      // Fetch status and list in parallel
      const [statusRes, listRes] = await Promise.all([
        fetch(`${API_BASE}/api/passkey/status`, { headers: getAuthHeaders() }),
        fetch(`${API_BASE}/api/passkey/list`, { headers: getAuthHeaders() })
      ])

      if (statusRes.ok) {
        const statusData: PasskeyStatus = await statusRes.json()
        setStatus(statusData)
      }

      if (listRes.ok) {
        const listData: PasskeyListResponse = await listRes.json()
        setPasskeys(listData.passkeys)
      }

      setViewState('list')
    } catch (err) {
      setError('Failed to connect to server')
      setViewState('error')
    }
  }

  const startRegistration = async () => {
    if (!browserSupported) {
      setError('Your browser does not support passkeys')
      return
    }

    try {
      setIsSubmitting(true)
      setError(null)

      // Get registration options from server
      const optionsRes = await fetch(`${API_BASE}/api/passkey/register-options`, {
        method: 'POST',
        headers: {
          ...getAuthHeaders(),
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ device_name: deviceName || getDefaultDeviceName() })
      })

      if (!optionsRes.ok) {
        const errorData = await optionsRes.json()
        throw new Error(errorData.detail || 'Failed to get registration options')
      }

      const optionsData = await optionsRes.json()
      const options = JSON.parse(optionsData.options)

      // Convert base64url strings to ArrayBuffers for WebAuthn API
      const publicKeyOptions: PublicKeyCredentialCreationOptions = {
        ...options,
        challenge: base64UrlToArrayBuffer(options.challenge),
        user: {
          ...options.user,
          id: base64UrlToArrayBuffer(options.user.id)
        },
        excludeCredentials: options.excludeCredentials?.map((cred: any) => ({
          ...cred,
          id: base64UrlToArrayBuffer(cred.id)
        })) || []
      }

      // Create credential with authenticator
      const credential = await navigator.credentials.create({
        publicKey: publicKeyOptions
      }) as PublicKeyCredential

      if (!credential) {
        throw new Error('Passkey creation was cancelled')
      }

      // Prepare credential for server
      const attestationResponse = credential.response as AuthenticatorAttestationResponse
      const credentialData = {
        id: credential.id,
        rawId: arrayBufferToBase64Url(credential.rawId),
        type: credential.type,
        response: {
          clientDataJSON: arrayBufferToBase64Url(attestationResponse.clientDataJSON),
          attestationObject: arrayBufferToBase64Url(attestationResponse.attestationObject)
        }
      }

      // Send credential to server
      const registerRes = await fetch(`${API_BASE}/api/passkey/register`, {
        method: 'POST',
        headers: {
          ...getAuthHeaders(),
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          credential: JSON.stringify(credentialData),
          device_name: deviceName || getDefaultDeviceName()
        })
      })

      if (!registerRes.ok) {
        const errorData = await registerRes.json()
        throw new Error(errorData.detail || 'Failed to register passkey')
      }

      // Success - refresh the list
      setDeviceName('')
      await fetchStatus()

    } catch (err: any) {
      if (err.name === 'NotAllowedError') {
        setError('Passkey creation was cancelled or timed out')
      } else {
        setError(err.message || 'Failed to register passkey')
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  const deletePasskey = async (id: number) => {
    if (!confirm('Are you sure you want to delete this passkey? You will need to use 2FA on this device.')) {
      return
    }

    try {
      setDeletingId(id)
      setError(null)

      const response = await fetch(`${API_BASE}/api/passkey/${id}`, {
        method: 'DELETE',
        headers: getAuthHeaders()
      })

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || 'Failed to delete passkey')
      }

      // Refresh the list
      await fetchStatus()

    } catch (err: any) {
      setError(err.message || 'Failed to delete passkey')
    } finally {
      setDeletingId(null)
    }
  }

  const getDefaultDeviceName = (): string => {
    const ua = navigator.userAgent
    if (ua.includes('iPhone')) return 'iPhone'
    if (ua.includes('iPad')) return 'iPad'
    if (ua.includes('Android')) return 'Android Device'
    if (ua.includes('Mac')) return 'Mac'
    if (ua.includes('Windows')) return 'Windows PC'
    if (ua.includes('Linux')) return 'Linux PC'
    return 'Unknown Device'
  }

  const getDeviceIcon = (name: string | null) => {
    const lowerName = (name || '').toLowerCase()
    if (lowerName.includes('iphone') || lowerName.includes('android') || lowerName.includes('phone')) {
      return <Smartphone className="w-5 h-5" />
    }
    return <Laptop className="w-5 h-5" />
  }

  const formatDate = (dateStr: string | null): string => {
    if (!dateStr) return 'Never'
    try {
      return new Date(dateStr).toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
      })
    } catch {
      return dateStr
    }
  }

  // Browser not supported
  if (!browserSupported) {
    return (
      <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-4">
        <div className="flex items-center gap-3 text-yellow-400">
          <AlertTriangle className="w-5 h-5" />
          <div>
            <p className="font-medium">Passkeys Not Supported</p>
            <p className="text-sm text-gray-400 mt-1">
              Your browser doesn't support passkeys (WebAuthn). Try using a modern browser like Chrome, Safari, Firefox, or Edge.
            </p>
          </div>
        </div>
      </div>
    )
  }

  // Loading state
  if (viewState === 'loading') {
    return (
      <div className="flex items-center justify-center p-8">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
      </div>
    )
  }

  // Server not available
  if (!status?.available) {
    return (
      <div className="bg-gray-800 rounded-lg p-4">
        <div className="flex items-center gap-3 text-gray-400">
          <Key className="w-5 h-5" />
          <div>
            <p className="font-medium">Passkeys Not Available</p>
            <p className="text-sm mt-1">
              Passkey authentication is not available on the server.
            </p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Fingerprint className="w-6 h-6 text-blue-400" />
          <div>
            <h3 className="font-medium text-white">Passkeys</h3>
            <p className="text-sm text-gray-400">
              {passkeys.length > 0
                ? `${passkeys.length} passkey${passkeys.length > 1 ? 's' : ''} registered`
                : 'Use biometrics or security keys instead of 2FA codes'}
            </p>
          </div>
        </div>
      </div>

      {/* Error display */}
      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3">
          <div className="flex items-center gap-2 text-red-400">
            <AlertTriangle className="w-4 h-4" />
            <span className="text-sm">{error}</span>
          </div>
        </div>
      )}

      {/* Info banner */}
      <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-3">
        <div className="flex items-start gap-2 text-blue-400">
          <Shield className="w-4 h-4 mt-0.5" />
          <div className="text-sm">
            <p className="font-medium">What are passkeys?</p>
            <p className="text-gray-400 mt-1">
              Passkeys let you sign in with fingerprint, face recognition, or your device PIN instead of entering 2FA codes.
              Once registered, you can skip 2FA on this device.
            </p>
          </div>
        </div>
      </div>

      {/* Registered passkeys list */}
      {passkeys.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-gray-300">Registered Passkeys</h4>
          <div className="space-y-2">
            {passkeys.map((passkey) => (
              <div
                key={passkey.id}
                className="flex items-center justify-between bg-gray-800 rounded-lg p-3"
              >
                <div className="flex items-center gap-3">
                  <div className="text-gray-400">
                    {getDeviceIcon(passkey.device_name)}
                  </div>
                  <div>
                    <p className="text-white font-medium">
                      {passkey.device_name || 'Unnamed Device'}
                    </p>
                    <p className="text-xs text-gray-500">
                      Added {formatDate(passkey.created_at)}
                      {passkey.last_used_at && ` · Last used ${formatDate(passkey.last_used_at)}`}
                    </p>
                  </div>
                </div>
                <button
                  onClick={() => deletePasskey(passkey.id)}
                  disabled={deletingId === passkey.id}
                  className="p-2 text-gray-400 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors disabled:opacity-50"
                  title="Delete passkey"
                >
                  {deletingId === passkey.id ? (
                    <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-red-400"></div>
                  ) : (
                    <Trash2 className="w-4 h-4" />
                  )}
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Register new passkey */}
      <div className="bg-gray-800 rounded-lg p-4">
        <h4 className="text-sm font-medium text-gray-300 mb-3">Register New Passkey</h4>
        <div className="space-y-3">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Device Name (optional)</label>
            <input
              type="text"
              value={deviceName}
              onChange={(e) => setDeviceName(e.target.value)}
              placeholder={getDefaultDeviceName()}
              className="w-full px-3 py-2 bg-gray-900 border border-gray-700 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <button
            onClick={startRegistration}
            disabled={isSubmitting}
            className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-800 disabled:cursor-not-allowed text-white rounded-lg transition-colors"
          >
            {isSubmitting ? (
              <>
                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                <span>Waiting for authenticator...</span>
              </>
            ) : (
              <>
                <Plus className="w-4 h-4" />
                <span>Add Passkey</span>
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}

export default PasskeySettings
