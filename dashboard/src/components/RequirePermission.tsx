import { Navigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { ReactNode } from 'react'

interface RequirePermissionProps {
  permission: string
  children: ReactNode
  redirectTo?: string
}

/**
 * Component that protects routes based on user permissions.
 * If the user doesn't have the required permission, redirects to the specified route.
 */
function RequirePermission({ permission, children, redirectTo = '/' }: RequirePermissionProps) {
  const { hasPermission, isLoading } = useAuth()

  // Show loading state while checking auth
  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-900">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500 mx-auto"></div>
          <p className="mt-4 text-gray-400">Checking permissions...</p>
        </div>
      </div>
    )
  }

  // If user doesn't have permission, redirect
  if (!hasPermission(permission)) {
    return <Navigate to={redirectTo} replace />
  }

  // User has permission, render the protected content
  return <>{children}</>
}

export default RequirePermission
