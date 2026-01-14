import { createContext, useContext, useState, useEffect, ReactNode } from 'react'

// API base URL from environment or empty for same-origin requests (required for Docker)
// In Docker, nginx proxies /api to the backend, so relative URLs work correctly
const API_BASE = (import.meta as any).env?.VITE_API_URL || ''

interface AuthStatus {
  auth_required: boolean
  jwt_available: boolean
  message: string
}

interface User {
  username: string
  email: string | null
  is_admin: boolean
  role: string
  last_login: string | null
}

// Permission mapping - must match backend ROLE_PERMISSIONS
const ROLE_PERMISSIONS: Record<string, Set<string>> = {
  admin: new Set(['*']),
  viewer: new Set([
    'dashboard:read', 'performance:read', 'trades:read',
    'config:read', 'indicators:read', 'regime:read',
    'status:read', 'self:password', 'self:2fa', 'self:passkey',
  ]),
}

interface AuthContextType {
  isAuthenticated: boolean
  isAuthRequired: boolean
  isLoading: boolean
  requires2FA: boolean
  requiresPasskey: boolean
  passkeyOptions: string | null
  pendingUsername: string | null
  user: User | null
  error: string | null
  isAdmin: boolean
  role: string | null
  hasPermission: (permission: string) => boolean
  login: (username: string, password: string) => Promise<boolean>
  loginWith2FA: (username: string, password: string, totpCode: string) => Promise<boolean>
  loginWithPasskey: (username: string, credential: string) => Promise<boolean>
  cancel2FA: () => void
  cancelPasskey: () => void
  logout: () => void
  checkAuthStatus: () => Promise<void>
}

const AuthContext = createContext<AuthContextType | null>(null)

const TOKEN_KEY = 'jutsu_auth_token'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [isAuthRequired, setIsAuthRequired] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [user, setUser] = useState<User | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(TOKEN_KEY))

  // 2FA state
  const [requires2FA, setRequires2FA] = useState(false)
  const [pendingUsername, setPendingUsername] = useState<string | null>(null)
  const [_pendingPassword, setPendingPassword] = useState<string | null>(null)

  // Passkey state
  const [requiresPasskey, setRequiresPasskey] = useState(false)
  const [passkeyOptions, setPasskeyOptions] = useState<string | null>(null)

  // Check auth status on mount
  useEffect(() => {
    checkAuthStatus()
  }, [])

  // Verify token on mount if present
  useEffect(() => {
    if (token && isAuthRequired) {
      verifyToken()
    }
  }, [token, isAuthRequired])

  const checkAuthStatus = async () => {
    try {
      setIsLoading(true)
      const response = await fetch(`${API_BASE}/api/auth/status`)
      if (response.ok) {
        const status: AuthStatus = await response.json()
        setIsAuthRequired(status.auth_required)

        // If auth not required, consider user as authenticated
        if (!status.auth_required) {
          setIsAuthenticated(true)
          setUser({ username: 'anonymous', email: null, is_admin: true, role: 'admin', last_login: null })
        }
      }
    } catch (err) {
      console.error('Failed to check auth status:', err)
      // On error, assume auth is not required (development mode)
      setIsAuthRequired(false)
      setIsAuthenticated(true)
    } finally {
      setIsLoading(false)
    }
  }

  const verifyToken = async () => {
    if (!token) {
      setIsAuthenticated(false)
      return
    }

    try {
      const response = await fetch(`${API_BASE}/api/auth/me`, {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      })

      if (response.ok) {
        const userData: User = await response.json()
        setUser(userData)
        setIsAuthenticated(true)
        setError(null)
      } else {
        // Token invalid or expired
        localStorage.removeItem(TOKEN_KEY)
        setToken(null)
        setIsAuthenticated(false)
        setUser(null)
      }
    } catch (err) {
      console.error('Failed to verify token:', err)
      setIsAuthenticated(false)
    }
  }

  const login = async (username: string, password: string): Promise<boolean> => {
    setError(null)
    setIsLoading(true)

    try {
      const formData = new URLSearchParams()
      formData.append('username', username)
      formData.append('password', password)

      const response = await fetch(`${API_BASE}/api/auth/login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: formData.toString(),
      })

      if (response.ok) {
        const data = await response.json()

        // Check if passkey is available (takes priority over 2FA)
        if (data.requires_passkey) {
          setPendingUsername(username)
          setPendingPassword(password)
          setPasskeyOptions(data.passkey_options)
          setRequiresPasskey(true)
          setIsLoading(false)
          return false // Not fully logged in yet, passkey required
        }

        // Check if 2FA is required (fallback if no passkey)
        if (data.requires_2fa) {
          setPendingUsername(username)
          setPendingPassword(password)
          setRequires2FA(true)
          setIsLoading(false)
          return false // Not fully logged in yet
        }

        const newToken = data.access_token

        // Store token
        localStorage.setItem(TOKEN_KEY, newToken)
        setToken(newToken)

        // Fetch user info
        const userResponse = await fetch(`${API_BASE}/api/auth/me`, {
          headers: {
            'Authorization': `Bearer ${newToken}`
          }
        })

        if (userResponse.ok) {
          const userData: User = await userResponse.json()
          setUser(userData)
        }

        setIsAuthenticated(true)
        return true
      } else {
        const errorData = await response.json()
        setError(errorData.detail || 'Login failed')
        return false
      }
    } catch (err) {
      console.error('Login error:', err)
      setError('Failed to connect to server')
      return false
    } finally {
      setIsLoading(false)
    }
  }

  const loginWith2FA = async (username: string, password: string, totpCode: string): Promise<boolean> => {
    setError(null)
    setIsLoading(true)

    try {
      const response = await fetch(`${API_BASE}/api/auth/login-2fa`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          username,
          password,
          totp_code: totpCode,
        }),
      })

      if (response.ok) {
        const data = await response.json()
        const newToken = data.access_token

        // Store token
        localStorage.setItem(TOKEN_KEY, newToken)
        setToken(newToken)

        // Clear 2FA state
        setRequires2FA(false)
        setPendingUsername(null)
        setPendingPassword(null)

        // Fetch user info
        const userResponse = await fetch(`${API_BASE}/api/auth/me`, {
          headers: {
            'Authorization': `Bearer ${newToken}`
          }
        })

        if (userResponse.ok) {
          const userData: User = await userResponse.json()
          setUser(userData)
        }

        setIsAuthenticated(true)
        return true
      } else {
        const errorData = await response.json()
        setError(errorData.detail || '2FA verification failed')
        return false
      }
    } catch (err) {
      console.error('2FA login error:', err)
      setError('Failed to connect to server')
      return false
    } finally {
      setIsLoading(false)
    }
  }

  const cancel2FA = () => {
    setRequires2FA(false)
    setPendingUsername(null)
    setPendingPassword(null)
    setError(null)
  }

  const cancelPasskey = () => {
    setRequiresPasskey(false)
    setPasskeyOptions(null)
    // Fall back to 2FA - passkeys are only available for users with 2FA enabled
    setRequires2FA(true)
    setError(null)
  }

  const loginWithPasskey = async (username: string, credential: string): Promise<boolean> => {
    setError(null)
    setIsLoading(true)

    try {
      const response = await fetch(`${API_BASE}/api/passkey/authenticate`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          username,
          credential,
        }),
      })

      if (response.ok) {
        const data = await response.json()
        const newToken = data.access_token

        // Store token
        localStorage.setItem(TOKEN_KEY, newToken)
        setToken(newToken)

        // Clear passkey state
        setRequiresPasskey(false)
        setPasskeyOptions(null)
        setPendingUsername(null)
        setPendingPassword(null)

        // Fetch user info
        const userResponse = await fetch(`${API_BASE}/api/auth/me`, {
          headers: {
            'Authorization': `Bearer ${newToken}`
          }
        })

        if (userResponse.ok) {
          const userData: User = await userResponse.json()
          setUser(userData)
        }

        setIsAuthenticated(true)
        return true
      } else {
        const errorData = await response.json()
        setError(errorData.detail || 'Passkey verification failed')
        return false
      }
    } catch (err) {
      console.error('Passkey login error:', err)
      setError('Failed to connect to server')
      return false
    } finally {
      setIsLoading(false)
    }
  }

  const logout = () => {
    localStorage.removeItem(TOKEN_KEY)
    setToken(null)
    setIsAuthenticated(false)
    setUser(null)
    setError(null)

    // Optionally call logout endpoint
    fetch(`${API_BASE}/api/auth/logout`, { method: 'POST' }).catch(() => {})
  }

  // Derived permission values
  const role = user?.role ?? null
  const isAdmin = user?.role === 'admin' || user?.is_admin === true

  // Permission check function
  const hasPermission = (permission: string): boolean => {
    if (!user) return false
    const userRole = user.role || 'viewer'
    const permissions = ROLE_PERMISSIONS[userRole] || new Set()
    return permissions.has('*') || permissions.has(permission)
  }

  return (
    <AuthContext.Provider
      value={{
        isAuthenticated,
        isAuthRequired,
        isLoading,
        requires2FA,
        requiresPasskey,
        passkeyOptions,
        pendingUsername,
        user,
        error,
        isAdmin,
        role,
        hasPermission,
        login,
        loginWith2FA,
        loginWithPasskey,
        cancel2FA,
        cancelPasskey,
        logout,
        checkAuthStatus,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}

// Helper to get auth headers for API calls
export function getAuthHeaders(): HeadersInit {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) {
    return {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json',
    }
  }
  return {
    'Content-Type': 'application/json',
  }
}
