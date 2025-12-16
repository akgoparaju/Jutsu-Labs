import { User, Shield } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import TwoFactorSettings from '../components/TwoFactorSettings'
import PasskeySettings from '../components/PasskeySettings'

function Settings() {
  const { user, isAuthRequired } = useAuth()

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div>
        <h1 className="text-2xl font-bold text-white">Settings</h1>
        <p className="text-gray-400 mt-1">Manage your account and security settings</p>
      </div>

      {/* Account Information */}
      {isAuthRequired && user && (
        <div className="bg-slate-800 rounded-lg p-6">
          <div className="flex items-start gap-4">
            <div className="p-3 bg-slate-700 rounded-lg">
              <User className="w-6 h-6 text-blue-400" />
            </div>
            <div className="flex-1">
              <h3 className="text-lg font-semibold text-white mb-1">Account Information</h3>
              <div className="space-y-2 text-sm">
                <div className="flex items-center gap-2">
                  <span className="text-gray-400 w-24">Username:</span>
                  <span className="text-white">{user.username}</span>
                </div>
                {user.email && (
                  <div className="flex items-center gap-2">
                    <span className="text-gray-400 w-24">Email:</span>
                    <span className="text-white">{user.email}</span>
                  </div>
                )}
                <div className="flex items-center gap-2">
                  <span className="text-gray-400 w-24">Role:</span>
                  <span className={`px-2 py-0.5 rounded-full text-xs ${
                    user.is_admin 
                      ? 'bg-purple-500/20 text-purple-400' 
                      : 'bg-gray-500/20 text-gray-400'
                  }`}>
                    {user.is_admin ? 'Administrator' : 'User'}
                  </span>
                </div>
                {user.last_login && (
                  <div className="flex items-center gap-2">
                    <span className="text-gray-400 w-24">Last Login:</span>
                    <span className="text-white">
                      {new Date(user.last_login).toLocaleString()}
                    </span>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Security Section Header */}
      {isAuthRequired && (
        <div className="flex items-center gap-2 mt-8">
          <Shield className="w-5 h-5 text-gray-400" />
          <h2 className="text-lg font-semibold text-white">Security</h2>
        </div>
      )}

      {/* Two-Factor Authentication */}
      {isAuthRequired && <TwoFactorSettings />}

      {/* Passkey Authentication */}
      {isAuthRequired && (
        <div className="bg-slate-800 rounded-lg p-6">
          <PasskeySettings />
        </div>
      )}

      {/* Auth not required message */}
      {!isAuthRequired && (
        <div className="bg-slate-800 rounded-lg p-6">
          <div className="text-center py-8">
            <Shield className="w-12 h-12 text-gray-600 mx-auto mb-4" />
            <h3 className="text-lg font-semibold text-white mb-2">Authentication Disabled</h3>
            <p className="text-gray-400 max-w-md mx-auto">
              Security settings are only available when authentication is enabled.
              Set <code className="px-1 py-0.5 bg-gray-700 rounded">AUTH_REQUIRED=true</code> in your environment to enable.
            </p>
          </div>
        </div>
      )}
    </div>
  )
}

export default Settings
