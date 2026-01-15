/**
 * ResponsiveLayout - Adaptive Layout Wrapper for V2 Routes
 *
 * Provides a responsive layout that adapts to device size:
 * - Mobile (<640px): Bottom navigation + header
 * - Tablet (640-1023px): Collapsible sidebar + header
 * - Desktop (1024px+): Full sidebar always visible
 *
 * Features:
 * - Proper spacing for sidebar (lg:ml-64)
 * - Bottom padding for mobile nav (pb-20 sm:pb-0)
 * - Responsive content padding
 * - Header with status indicators and user controls
 * - Permission-preserved from v1 Layout
 *
 * @version 1.0.0
 * @part Responsive UI - Phase 2.4
 */

import { Outlet, useNavigate } from 'react-router-dom'
import {
  Wifi,
  WifiOff,
  LogOut,
  User,
} from 'lucide-react'
import { CollapsibleSidebar } from '../components/navigation/CollapsibleSidebar'
import { MobileBottomNav } from '../components/navigation/MobileBottomNav'
import { useStatus } from '../hooks/useStatus'
import { useLiveUpdates } from '../hooks/useWebSocket'
import { useAuth } from '../contexts/AuthContext'
import logoImg from '../assets/logo.svg'

/**
 * Safely format a date string for display.
 */
function formatDateTime(isoString: string | null | undefined): string {
  if (!isoString) return 'N/A'
  try {
    let normalized = isoString
    const microMatch = isoString.match(/(\.\d{3})\d+/)
    if (microMatch) {
      normalized = isoString.replace(/(\.\d{3})\d+/, '$1')
    }
    const date = new Date(normalized)
    if (isNaN(date.getTime())) {
      return 'N/A'
    }
    return date.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
    })
  } catch {
    return 'N/A'
  }
}

function ResponsiveLayout() {
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
      <header className="fixed top-0 left-0 right-0 z-30 bg-slate-800 border-b border-slate-700 lg:pl-64">
        <div className="px-4 py-3 sm:px-6 sm:py-4">
          <div className="flex items-center justify-between">
            {/* Left: Logo (mobile only) / Spacer (tablet/desktop) */}
            <div className="flex items-center gap-3">
              {/* Logo shown only on mobile (sidebar hidden) */}
              <div className="flex items-center gap-2 sm:hidden">
                <img
                  src={logoImg}
                  alt="Jutsu Trading Logo"
                  className="w-8 h-8 object-contain"
                />
                <span className="text-lg font-bold">Jutsu</span>
              </div>
              {/* Spacer for tablet (where hamburger is positioned) */}
              <div className="hidden sm:block lg:hidden w-12" />
            </div>

            {/* Right: Status indicators */}
            <div className="flex items-center gap-2 sm:gap-4">
              {/* Data Updated timestamp - hidden on mobile */}
              {status?.last_execution && (
                <div className="hidden md:block text-xs text-gray-500">
                  Updated: {formatDateTime(status.last_execution)}
                </div>
              )}

              {/* WebSocket status */}
              <div
                className="flex items-center"
                title={wsConnected ? 'Live updates active' : 'Live updates disconnected'}
              >
                {wsConnected ? (
                  <Wifi className="w-4 h-4 text-green-400" />
                ) : (
                  <WifiOff className="w-4 h-4 text-red-400" />
                )}
              </div>

              {/* Engine status */}
              {!isLoading && (
                <>
                  <div className="flex items-center gap-1.5">
                    <span className={`w-2 h-2 rounded-full ${
                      status?.is_running ? 'bg-green-500' : 'bg-gray-500'
                    }`} />
                    <span className="hidden sm:inline text-sm text-gray-300">
                      {status?.is_running ? 'Running' : 'Stopped'}
                    </span>
                  </div>

                  <div className="px-2 sm:px-3 py-1 rounded-full text-xs font-medium bg-slate-700">
                    {status?.mode === 'online_live' ? (
                      <span className="text-yellow-400">LIVE</span>
                    ) : (
                      <span className="text-blue-400">PAPER</span>
                    )}
                  </div>
                </>
              )}

              {/* User info and logout */}
              {isAuthRequired && user && (
                <div className="flex items-center gap-2 ml-2 pl-2 border-l border-slate-600">
                  <div className="hidden sm:flex items-center gap-1.5 text-sm text-gray-300">
                    <User className="w-4 h-4" />
                    <span className="hidden md:inline">{user.username}</span>
                  </div>
                  <button
                    onClick={handleLogout}
                    className="flex items-center justify-center p-2 min-w-[44px] min-h-[44px] sm:min-w-0 sm:min-h-0 sm:px-3 sm:py-1.5 text-sm text-gray-400 hover:text-white hover:bg-slate-700 rounded-lg transition-colors"
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

      {/* Sidebar - hidden on mobile, toggleable on tablet, fixed on desktop */}
      <CollapsibleSidebar />

      {/* Main Content */}
      <main
        className={`
          min-h-screen
          pt-16
          lg:ml-64
          pb-20 sm:pb-6
          px-4 sm:px-6 md:px-8
        `}
      >
        <Outlet />
      </main>

      {/* Bottom Navigation - mobile only */}
      <MobileBottomNav />
    </div>
  )
}

export default ResponsiveLayout
