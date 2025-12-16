import { useState, FormEvent, useEffect } from 'react'
import { Navigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'

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

function Login() {
  const {
    isAuthenticated,
    isAuthRequired,
    isLoading,
    error,
    login,
    requires2FA,
    requiresPasskey,
    passkeyOptions,
    pendingUsername,
    loginWith2FA,
    loginWithPasskey,
    cancel2FA,
    cancelPasskey
  } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [totpCode, setTotpCode] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [passkeyError, setPasskeyError] = useState<string | null>(null)
  const [passkeyVerifying, setPasskeyVerifying] = useState(false)

  // Auto-trigger passkey authentication when requiresPasskey becomes true
  useEffect(() => {
    if (requiresPasskey && passkeyOptions && pendingUsername && !passkeyVerifying) {
      handlePasskeyAuthentication()
    }
  }, [requiresPasskey, passkeyOptions, pendingUsername])

  const handlePasskeyAuthentication = async () => {
    if (!passkeyOptions || !pendingUsername) return

    setPasskeyVerifying(true)
    setPasskeyError(null)

    try {
      // Parse the options from the server
      const options = JSON.parse(passkeyOptions)

      // Convert challenge from base64url to ArrayBuffer
      const publicKeyOptions: PublicKeyCredentialRequestOptions = {
        challenge: base64UrlToArrayBuffer(options.challenge),
        timeout: options.timeout || 60000,
        rpId: options.rpId,
        allowCredentials: options.allowCredentials?.map((cred: { id: string; type: string; transports?: string[] }) => ({
          id: base64UrlToArrayBuffer(cred.id),
          type: cred.type,
          transports: cred.transports,
        })),
        userVerification: options.userVerification || 'preferred',
      }

      // Call the WebAuthn API
      const credential = await navigator.credentials.get({
        publicKey: publicKeyOptions,
      }) as PublicKeyCredential

      if (!credential) {
        throw new Error('No credential received from authenticator')
      }

      // Get the response
      const response = credential.response as AuthenticatorAssertionResponse

      // Convert the credential to a format the server expects
      const credentialData = {
        id: credential.id,
        rawId: arrayBufferToBase64Url(credential.rawId),
        type: credential.type,
        response: {
          clientDataJSON: arrayBufferToBase64Url(response.clientDataJSON),
          authenticatorData: arrayBufferToBase64Url(response.authenticatorData),
          signature: arrayBufferToBase64Url(response.signature),
          userHandle: response.userHandle ? arrayBufferToBase64Url(response.userHandle) : null,
        },
      }

      // Send to server for verification
      const success = await loginWithPasskey(pendingUsername, JSON.stringify(credentialData))

      if (!success) {
        setPasskeyError('Passkey verification failed. Please try again or use 2FA.')
      }
    } catch (err) {
      console.error('Passkey authentication error:', err)
      if (err instanceof Error) {
        if (err.name === 'NotAllowedError') {
          setPasskeyError('Authentication was cancelled or timed out.')
        } else if (err.name === 'SecurityError') {
          setPasskeyError('Security error: The operation is not allowed in this context.')
        } else {
          setPasskeyError(err.message || 'Failed to authenticate with passkey.')
        }
      } else {
        setPasskeyError('An unexpected error occurred during passkey authentication.')
      }
    } finally {
      setPasskeyVerifying(false)
    }
  }

  const handleCancelPasskey = () => {
    cancelPasskey()
    setPasskeyError(null)
    // Don't clear password - it's needed for 2FA fallback
  }

  // If auth not required or already authenticated, redirect to dashboard
  if (!isLoading && (!isAuthRequired || isAuthenticated)) {
    return <Navigate to="/" replace />
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!username || !password) return

    setIsSubmitting(true)
    await login(username, password)
    setIsSubmitting(false)
  }

  const handle2FASubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!totpCode || !pendingUsername) return

    setIsSubmitting(true)
    // We need to use the stored credentials from the context
    // The context stores them internally, we just call loginWith2FA
    const success = await loginWith2FA(pendingUsername!, password, totpCode)
    if (!success) {
      setTotpCode('') // Clear the code on failure so user can retry
    }
    setIsSubmitting(false)
  }

  const handleCancel2FA = () => {
    cancel2FA()
    setTotpCode('')
    setPassword('')
  }

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-900">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500 mx-auto"></div>
          <p className="mt-4 text-gray-400">Loading...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-900 px-4">
      <div className="max-w-md w-full">
        {/* Logo / Title */}
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-white">Jutsu Trading</h1>
          <p className="mt-2 text-gray-400">Sign in to access the dashboard</p>
        </div>

        {/* Login Form */}
        <div className="bg-gray-800 rounded-lg shadow-lg p-8">
          {/* Error Message */}
          {error && (
            <div className="bg-red-500/10 border border-red-500/50 rounded-lg p-4 mb-6">
              <p className="text-red-400 text-sm">{error}</p>
            </div>
          )}

          {requiresPasskey ? (
            /* Passkey Verification */
            <div className="space-y-6">
              <div className="text-center mb-4">
                <div className="inline-flex items-center justify-center w-12 h-12 bg-green-500/20 rounded-full mb-3">
                  <svg className="w-6 h-6 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
                  </svg>
                </div>
                <h3 className="text-lg font-medium text-white">Passkey Verification</h3>
                <p className="text-sm text-gray-400 mt-1">
                  {passkeyVerifying
                    ? 'Please verify your identity using your passkey...'
                    : 'Use your passkey to sign in securely'}
                </p>
              </div>

              {/* Loading State */}
              {passkeyVerifying && (
                <div className="flex flex-col items-center py-6">
                  <div className="animate-pulse">
                    <svg className="w-16 h-16 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 11c0 3.517-1.009 6.799-2.753 9.571m-3.44-2.04l.054-.09A13.916 13.916 0 008 11a4 4 0 118 0c0 1.017-.07 2.019-.203 3m-2.118 6.844A21.88 21.88 0 0015.171 17m3.839 1.132c.645-2.266.99-4.659.99-7.132A8 8 0 008 4.07M3 15.364c.64-1.319 1-2.8 1-4.364 0-1.457.39-2.823 1.07-4" />
                    </svg>
                  </div>
                  <p className="mt-4 text-gray-400">Waiting for authentication...</p>
                </div>
              )}

              {/* Error State */}
              {passkeyError && (
                <div className="bg-red-500/10 border border-red-500/50 rounded-lg p-4">
                  <p className="text-red-400 text-sm">{passkeyError}</p>
                </div>
              )}

              {/* Buttons */}
              <div className="flex flex-col gap-3">
                {!passkeyVerifying && (
                  <button
                    type="button"
                    onClick={handlePasskeyAuthentication}
                    className="w-full py-3 px-4 bg-green-600 hover:bg-green-700 text-white font-medium rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-2 focus:ring-offset-gray-800"
                  >
                    <span className="flex items-center justify-center">
                      <svg className="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
                      </svg>
                      Try Passkey Again
                    </span>
                  </button>
                )}
                <button
                  type="button"
                  onClick={handleCancelPasskey}
                  disabled={passkeyVerifying}
                  className="w-full py-3 px-4 bg-gray-700 hover:bg-gray-600 disabled:bg-gray-600 disabled:cursor-not-allowed text-white font-medium rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-gray-500 focus:ring-offset-2 focus:ring-offset-gray-800"
                >
                  Use 2FA Instead
                </button>
              </div>
            </div>
          ) : requires2FA ? (
            /* 2FA Verification Form */
            <form onSubmit={handle2FASubmit} className="space-y-6">
              <div className="text-center mb-4">
                <div className="inline-flex items-center justify-center w-12 h-12 bg-blue-500/20 rounded-full mb-3">
                  <svg className="w-6 h-6 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                  </svg>
                </div>
                <h3 className="text-lg font-medium text-white">Two-Factor Authentication</h3>
                <p className="text-sm text-gray-400 mt-1">
                  Enter the code from your authenticator app
                </p>
              </div>

              {/* TOTP Code Field */}
              <div>
                <label htmlFor="totp" className="block text-sm font-medium text-gray-300 mb-2">
                  Verification Code
                </label>
                <input
                  id="totp"
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9]*"
                  maxLength={6}
                  value={totpCode}
                  onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, ''))}
                  className="w-full px-4 py-3 bg-gray-700 border border-gray-600 rounded-lg text-white text-center text-2xl tracking-widest placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder="000000"
                  autoComplete="one-time-code"
                  autoFocus
                  disabled={isSubmitting}
                />
                <p className="text-xs text-gray-500 mt-2 text-center">
                  You can also use a backup code
                </p>
              </div>

              {/* Buttons */}
              <div className="flex gap-3">
                <button
                  type="button"
                  onClick={handleCancel2FA}
                  disabled={isSubmitting}
                  className="flex-1 py-3 px-4 bg-gray-700 hover:bg-gray-600 disabled:bg-gray-600 disabled:cursor-not-allowed text-white font-medium rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-gray-500 focus:ring-offset-2 focus:ring-offset-gray-800"
                >
                  Back
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting || totpCode.length < 6}
                  className="flex-1 py-3 px-4 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white font-medium rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-gray-800"
                >
                  {isSubmitting ? (
                    <span className="flex items-center justify-center">
                      <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                      </svg>
                      Verifying...
                    </span>
                  ) : (
                    'Verify'
                  )}
                </button>
              </div>
            </form>
          ) : (
            /* Standard Login Form */
            <form onSubmit={handleSubmit} className="space-y-6">
              {/* Username Field */}
              <div>
                <label htmlFor="username" className="block text-sm font-medium text-gray-300 mb-2">
                  Username
                </label>
                <input
                  id="username"
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="w-full px-4 py-3 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder="Enter your username"
                  autoComplete="username"
                  disabled={isSubmitting}
                />
              </div>

              {/* Password Field */}
              <div>
                <label htmlFor="password" className="block text-sm font-medium text-gray-300 mb-2">
                  Password
                </label>
                <input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full px-4 py-3 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder="Enter your password"
                  autoComplete="current-password"
                  disabled={isSubmitting}
                />
              </div>

              {/* Submit Button */}
              <button
                type="submit"
                disabled={isSubmitting || !username || !password}
                className="w-full py-3 px-4 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white font-medium rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-gray-800"
              >
                {isSubmitting ? (
                  <span className="flex items-center justify-center">
                    <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                    Signing in...
                  </span>
                ) : (
                  'Sign In'
                )}
              </button>
            </form>
          )}
        </div>

        {/* Footer */}
        <p className="mt-8 text-center text-sm text-gray-500">
          Jutsu Trading Engine - Quantitative Trading Platform
        </p>
      </div>
    </div>
  )
}

export default Login
