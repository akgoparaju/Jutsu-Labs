import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'

function ProtectedRoute() {
  const { isAuthenticated, isAuthRequired, isLoading } = useAuth()

  // Show loading state while checking auth
  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-900">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500 mx-auto"></div>
          <p className="mt-4 text-gray-400">Checking authentication...</p>
        </div>
      </div>
    )
  }

  // If auth not required, allow access
  if (!isAuthRequired) {
    return <Outlet />
  }

  // If auth required but not authenticated, redirect to login
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  // Authenticated, render the protected content
  return <Outlet />
}

export default ProtectedRoute
