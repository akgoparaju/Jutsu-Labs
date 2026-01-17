import { useState, useEffect } from 'react'
import { useSearchParams, Link } from 'react-router-dom'
import { usersApi } from '../api/client'
import { UserPlus, CheckCircle, XCircle, Loader2 } from 'lucide-react'

type Step = 'loading' | 'form' | 'success' | 'error'

/**
 * Extract a human-readable error message from API error response.
 * Handles both string errors and Pydantic validation error arrays.
 */
function extractErrorMessage(detail: unknown): string {
  // If it's a string, return directly
  if (typeof detail === 'string') {
    return detail
  }

  // If it's an array (Pydantic validation errors), extract messages
  if (Array.isArray(detail)) {
    const messages = detail.map((err: any) => {
      if (typeof err === 'string') return err
      // Pydantic error format: { loc: [...], msg: "...", type: "..." }
      if (err.msg) return err.msg
      return JSON.stringify(err)
    })
    return messages.join('. ')
  }

  // If it's an object with a message field
  if (detail && typeof detail === 'object' && 'message' in detail) {
    return String((detail as any).message)
  }

  // Fallback
  return 'An unexpected error occurred. Please try again.'
}

function AcceptInvitation() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token')

  const [step, setStep] = useState<Step>('loading')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  useEffect(() => {
    // Validate token exists
    if (!token) {
      setError('Invalid invitation link. No token provided.')
      setStep('error')
      return
    }

    // Token exists, show the form
    setStep('form')
  }, [token])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)

    const trimmedUsername = username.trim()

    // Validation
    if (!trimmedUsername) {
      setError('Username is required')
      return
    }
    if (trimmedUsername.length < 3) {
      setError('Username must be at least 3 characters')
      return
    }
    // Username format validation - must be alphanumeric with underscores only
    if (!/^[a-zA-Z0-9_]+$/.test(trimmedUsername)) {
      setError('Username can only contain letters, numbers, and underscores (no spaces or special characters like @)')
      return
    }
    if (!password) {
      setError('Password is required')
      return
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters')
      return
    }
    if (password !== confirmPassword) {
      setError('Passwords do not match')
      return
    }

    setIsSubmitting(true)

    try {
      await usersApi.acceptInvitation(token!, {
        username: trimmedUsername,
        password,
      })

      setStep('success')
    } catch (err: any) {
      // Extract error message, handling both string and array formats
      const detail = err.response?.data?.detail
      const errorMessage = detail
        ? extractErrorMessage(detail)
        : 'Failed to accept invitation. The link may have expired or already been used.'
      setError(errorMessage)

      // Only switch to error page for truly unrecoverable errors (invalid/expired token)
      if (err.response?.status === 400 || err.response?.status === 404) {
        setStep('error')
      }
      // For 422 (validation errors), stay on form so user can correct input
    } finally {
      setIsSubmitting(false)
    }
  }

  // Loading state
  if (step === 'loading') {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 flex items-center justify-center p-4">
        <div className="bg-slate-800 rounded-xl shadow-xl p-8 w-full max-w-md text-center">
          <Loader2 className="w-12 h-12 text-blue-400 animate-spin mx-auto mb-4" />
          <p className="text-gray-400">Validating invitation...</p>
        </div>
      </div>
    )
  }

  // Success state
  if (step === 'success') {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 flex items-center justify-center p-4">
        <div className="bg-slate-800 rounded-xl shadow-xl p-8 w-full max-w-md text-center">
          <CheckCircle className="w-16 h-16 text-green-400 mx-auto mb-4" />
          <h1 className="text-2xl font-bold text-white mb-2">Account Created!</h1>
          <p className="text-gray-400 mb-6">
            Your account has been successfully created.
            You can now log in with your credentials.
          </p>
          <Link
            to="/login"
            className="inline-block px-6 py-3 bg-blue-600 hover:bg-blue-700 rounded-lg font-medium text-white transition-colors"
          >
            Go to Login
          </Link>
        </div>
      </div>
    )
  }

  // Error state (invalid/expired token)
  if (step === 'error') {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 flex items-center justify-center p-4">
        <div className="bg-slate-800 rounded-xl shadow-xl p-8 w-full max-w-md text-center">
          <XCircle className="w-16 h-16 text-red-400 mx-auto mb-4" />
          <h1 className="text-2xl font-bold text-white mb-2">Invalid Invitation</h1>
          <p className="text-gray-400 mb-6">
            {error || 'This invitation link is invalid, has expired, or has already been used.'}
          </p>
          <p className="text-sm text-gray-500 mb-6">
            Please contact your administrator for a new invitation.
          </p>
          <Link
            to="/login"
            className="inline-block px-6 py-3 bg-slate-700 hover:bg-slate-600 rounded-lg font-medium text-white transition-colors"
          >
            Go to Login
          </Link>
        </div>
      </div>
    )
  }

  // Form state
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 flex items-center justify-center p-4">
      <div className="bg-slate-800 rounded-xl shadow-xl p-8 w-full max-w-md">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-blue-600/20 rounded-full mb-4">
            <UserPlus className="w-8 h-8 text-blue-400" />
          </div>
          <h1 className="text-2xl font-bold text-white">Accept Invitation</h1>
          <p className="text-gray-400 mt-2">Create your account to get started</p>
        </div>

        {/* Error Message */}
        {error && (
          <div className="mb-6 p-4 bg-red-900/30 border border-red-600 rounded-lg text-red-400 text-sm">
            {error}
          </div>
        )}

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">
              Username
            </label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="Choose a username"
              className="w-full px-4 py-3 bg-slate-700 border border-slate-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:border-blue-500 transition-colors"
              autoComplete="username"
              autoFocus
            />
            <p className="mt-1 text-xs text-gray-500">Letters, numbers, and underscores only (not email)</p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Create a password"
              className="w-full px-4 py-3 bg-slate-700 border border-slate-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:border-blue-500 transition-colors"
              autoComplete="new-password"
            />
            <p className="mt-1 text-xs text-gray-500">At least 8 characters</p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">
              Confirm Password
            </label>
            <input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="Confirm your password"
              className="w-full px-4 py-3 bg-slate-700 border border-slate-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:border-blue-500 transition-colors"
              autoComplete="new-password"
            />
          </div>

          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full py-3 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-800 disabled:cursor-not-allowed rounded-lg font-medium text-white transition-colors flex items-center justify-center gap-2"
          >
            {isSubmitting ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                Creating Account...
              </>
            ) : (
              'Create Account'
            )}
          </button>
        </form>

        {/* Footer */}
        <div className="mt-6 text-center">
          <p className="text-sm text-gray-400">
            Already have an account?{' '}
            <Link to="/login" className="text-blue-400 hover:text-blue-300">
              Log in
            </Link>
          </p>
        </div>
      </div>
    </div>
  )
}

export default AcceptInvitation
