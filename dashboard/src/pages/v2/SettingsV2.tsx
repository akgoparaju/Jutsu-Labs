/**
 * SettingsV2 - Responsive Settings Page
 *
 * Fully responsive settings page with account info, 2FA, passkeys, and user management.
 *
 * @version 2.0.0
 * @part Responsive UI - Phase 4
 */

import { User, Shield, Users } from 'lucide-react'
import { useAuth } from '../../contexts/AuthContext'
import TwoFactorSettings from '../../components/TwoFactorSettings'
import PasskeySettings from '../../components/PasskeySettings'
import UserManagement from '../../components/UserManagement'
import { ResponsiveCard, ResponsiveText } from '../../components/ui'

function SettingsV2() {
  const { user, isAuthRequired, hasPermission } = useAuth()

  return (
    <div className="space-y-4 sm:space-y-6">
      {/* Page Header */}
      <div>
        <ResponsiveText variant="h1" as="h1" className="text-white">
          Settings
        </ResponsiveText>
        <ResponsiveText variant="body" className="text-gray-400 mt-1">
          Manage your account and security settings
        </ResponsiveText>
      </div>

      {/* Account Information */}
      {isAuthRequired && user && (
        <ResponsiveCard padding="md">
          <div className="flex flex-col sm:flex-row items-start gap-4">
            <div className="p-3 bg-slate-700 rounded-lg shrink-0">
              <User className="w-6 h-6 text-blue-400" />
            </div>
            <div className="flex-1 w-full">
              <ResponsiveText variant="h3" as="h3" className="text-white mb-3">
                Account Information
              </ResponsiveText>
              <div className="space-y-2 text-sm">
                <div className="flex flex-col xs:flex-row xs:items-center gap-1 xs:gap-2">
                  <span className="text-gray-400 xs:w-24 shrink-0">Username:</span>
                  <span className="text-white">{user.username}</span>
                </div>
                {user.email && (
                  <div className="flex flex-col xs:flex-row xs:items-center gap-1 xs:gap-2">
                    <span className="text-gray-400 xs:w-24 shrink-0">Email:</span>
                    <span className="text-white break-all">{user.email}</span>
                  </div>
                )}
                <div className="flex flex-col xs:flex-row xs:items-center gap-1 xs:gap-2">
                  <span className="text-gray-400 xs:w-24 shrink-0">Role:</span>
                  <span className={`px-2 py-0.5 rounded-full text-xs inline-block ${
                    user.role === 'admin'
                      ? 'bg-purple-500/20 text-purple-400'
                      : 'bg-gray-500/20 text-gray-400'
                  }`}>
                    {user.role === 'admin' ? 'Administrator' : 'Viewer'}
                  </span>
                </div>
                {user.last_login && (
                  <div className="flex flex-col xs:flex-row xs:items-center gap-1 xs:gap-2">
                    <span className="text-gray-400 xs:w-24 shrink-0">Last Login:</span>
                    <span className="text-white">
                      {new Date(user.last_login).toLocaleString()}
                    </span>
                  </div>
                )}
              </div>
            </div>
          </div>
        </ResponsiveCard>
      )}

      {/* Security Section Header */}
      {isAuthRequired && (
        <div className="flex items-center gap-2 mt-6 sm:mt-8">
          <Shield className="w-5 h-5 text-gray-400" />
          <ResponsiveText variant="h2" as="h2" className="text-white">
            Security
          </ResponsiveText>
        </div>
      )}

      {/* Two-Factor Authentication */}
      {isAuthRequired && <TwoFactorSettings />}

      {/* Passkey Authentication */}
      {isAuthRequired && (
        <ResponsiveCard padding="md">
          <PasskeySettings />
        </ResponsiveCard>
      )}

      {/* User Management - Admin Only */}
      {isAuthRequired && hasPermission('users:manage') && (
        <>
          <div className="flex items-center gap-2 mt-6 sm:mt-8">
            <Users className="w-5 h-5 text-gray-400" />
            <ResponsiveText variant="h2" as="h2" className="text-white">
              User Management
            </ResponsiveText>
          </div>
          <UserManagement />
        </>
      )}

      {/* Auth not required message */}
      {!isAuthRequired && (
        <ResponsiveCard padding="md">
          <div className="text-center py-6 sm:py-8">
            <Shield className="w-10 h-10 sm:w-12 sm:h-12 text-gray-600 mx-auto mb-4" />
            <ResponsiveText variant="h3" as="h3" className="text-white mb-2">
              Authentication Disabled
            </ResponsiveText>
            <ResponsiveText variant="body" className="text-gray-400 max-w-md mx-auto">
              Security settings are only available when authentication is enabled.
              Set <code className="px-1 py-0.5 bg-gray-700 rounded text-xs sm:text-sm">AUTH_REQUIRED=true</code> in your environment to enable.
            </ResponsiveText>
          </div>
        </ResponsiveCard>
      )}
    </div>
  )
}

export default SettingsV2
