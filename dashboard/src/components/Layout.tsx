import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard,
  TrendingUp,
  History,
  Settings,
  Wifi,
  WifiOff,
  GitBranch,
  LogOut,
  User,
} from 'lucide-react'
import logoImg from '../assets/logo.svg'
import { useStatus } from '../hooks/useStatus'
import { useLiveUpdates } from '../hooks/useWebSocket'
import { useAuth } from '../contexts/AuthContext'

function Layout() {
  const { data: status, isLoading } = useStatus()
  const { isConnected: wsConnected } = useLiveUpdates()
  const { user, isAuthRequired, logout } = useAuth()
  const navigate = useNavigate()

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  return (
    <div className="min-h-screen bg-slate-900 text-white">
      {/* Header */}
      <header className="bg-slate-800 border-b border-slate-700">
        <div className="max-w-7xl mx-auto px-4 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <img
                src={logoImg}
                alt="Jutsu Trading Logo"
                className="w-10 h-10 object-contain"
              />
              <h1 className="text-xl font-bold">Jutsu Trading</h1>
            </div>

            {/* Status indicator */}
            <div className="flex items-center gap-4">
              {/* Data Updated timestamp */}
              {status?.last_execution && (
                <div className="text-xs text-gray-500">
                  Last Updated: {new Date(
                    // Append 'Z' if missing to ensure UTC interpretation
                    status.last_execution.endsWith('Z') || status.last_execution.includes('+')
                      ? status.last_execution
                      : status.last_execution + 'Z'
                  ).toLocaleString('en-US', {
                    month: 'short',
                    day: 'numeric',
                    hour: 'numeric',
                    minute: '2-digit',
                    hour12: true,
                  })}
                </div>
              )}

              {/* WebSocket connection status */}
              <div className="flex items-center gap-1" title={wsConnected ? 'Live updates active' : 'Live updates disconnected'}>
                {wsConnected ? (
                  <Wifi className="w-4 h-4 text-green-400" />
                ) : (
                  <WifiOff className="w-4 h-4 text-red-400" />
                )}
              </div>

              {isLoading ? (
                <span className="text-gray-400">Loading...</span>
              ) : (
                <>
                  <div className="flex items-center gap-2">
                    <span className={`w-2 h-2 rounded-full ${
                      status?.is_running ? 'bg-green-500' : 'bg-gray-500'
                    }`} />
                    <span className="text-sm text-gray-300">
                      {status?.is_running ? 'Running' : 'Stopped'}
                    </span>
                  </div>
                  <div className="px-3 py-1 rounded-full text-xs font-medium bg-slate-700">
                    {status?.mode === 'online_live' ? (
                      <span className="text-yellow-400">LIVE TRADING</span>
                    ) : (
                      <span className="text-blue-400">PAPER TRADING</span>
                    )}
                  </div>
                </>
              )}

              {/* User info and logout (only show when auth is enabled) */}
              {isAuthRequired && user && (
                <div className="flex items-center gap-3 ml-4 pl-4 border-l border-slate-600">
                  <div className="flex items-center gap-2 text-sm text-gray-300">
                    <User className="w-4 h-4" />
                    <span>{user.username}</span>
                  </div>
                  <button
                    onClick={handleLogout}
                    className="flex items-center gap-1 px-3 py-1 text-sm text-gray-400 hover:text-white hover:bg-slate-700 rounded-lg transition-colors"
                    title="Sign out"
                  >
                    <LogOut className="w-4 h-4" />
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      </header>

      <div className="flex">
        {/* Sidebar */}
        <nav className="w-64 bg-slate-800 min-h-[calc(100vh-73px)] border-r border-slate-700">
          <div className="p-4 space-y-2">
            <NavLink
              to="/"
              className={({ isActive }) =>
                `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
                  isActive
                    ? 'bg-blue-600 text-white'
                    : 'text-gray-300 hover:bg-slate-700'
                }`
              }
            >
              <LayoutDashboard className="w-5 h-5" />
              Dashboard
            </NavLink>

            <NavLink
              to="/decision-tree"
              className={({ isActive }) =>
                `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
                  isActive
                    ? 'bg-blue-600 text-white'
                    : 'text-gray-300 hover:bg-slate-700'
                }`
              }
            >
              <GitBranch className="w-5 h-5" />
              Decision Tree
            </NavLink>

            <NavLink
              to="/performance"
              className={({ isActive }) =>
                `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
                  isActive
                    ? 'bg-blue-600 text-white'
                    : 'text-gray-300 hover:bg-slate-700'
                }`
              }
            >
              <TrendingUp className="w-5 h-5" />
              Performance
            </NavLink>

            <NavLink
              to="/trades"
              className={({ isActive }) =>
                `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
                  isActive
                    ? 'bg-blue-600 text-white'
                    : 'text-gray-300 hover:bg-slate-700'
                }`
              }
            >
              <History className="w-5 h-5" />
              Trade History
            </NavLink>

            <NavLink
              to="/config"
              className={({ isActive }) =>
                `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
                  isActive
                    ? 'bg-blue-600 text-white'
                    : 'text-gray-300 hover:bg-slate-700'
                }`
              }
            >
              <Settings className="w-5 h-5" />
              Configuration
            </NavLink>
          </div>
        </nav>

        {/* Main content */}
        <main className="flex-1 p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

export default Layout
