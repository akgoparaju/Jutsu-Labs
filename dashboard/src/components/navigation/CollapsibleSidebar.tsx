/**
 * CollapsibleSidebar - Responsive Sidebar Navigation
 *
 * Provides adaptive sidebar navigation across device sizes:
 * - Mobile (<640px): Hidden (use MobileBottomNav instead)
 * - Tablet (640-1023px): Toggleable sidebar with hamburger button
 * - Desktop (1024px+): Always visible, no toggle needed
 *
 * Features:
 * - Smooth slide-in/out animation (300ms)
 * - Backdrop overlay when open on tablet
 * - Close on nav item click
 * - Close on backdrop click
 * - Permission-aware navigation items
 * - 44px minimum touch targets
 *
 * @version 1.0.0
 * @part Responsive UI - Phase 2.3
 */

import { useState, useEffect } from 'react'
import { NavLink, Link, useLocation } from 'react-router-dom'
import {
  Menu,
  X,
  LayoutDashboard,
  GitBranch,
  TrendingUp,
  History,
  Settings,
  Shield,
  BarChart3,
} from 'lucide-react'
import { useAuth } from '../../contexts/AuthContext'
import { useIsDesktop } from '../../hooks/useMediaQuery'
import logoImg from '../../assets/logo.svg'

interface NavItem {
  path: string
  icon: React.ComponentType<{ className?: string }>
  label: string
  permission?: string
}

const navItems: NavItem[] = [
  { path: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { path: '/decision-tree', icon: GitBranch, label: 'Decision Tree' },
  { path: '/performance', icon: TrendingUp, label: 'Performance' },
  { path: '/trades', icon: History, label: 'Trade History' },
  { path: '/config', icon: Settings, label: 'Configuration', permission: 'config:write' },
  { path: '/backtest', icon: BarChart3, label: 'Backtest' },
  { path: '/settings', icon: Shield, label: 'Settings' },
]

interface CollapsibleSidebarProps {
  className?: string
}

export function CollapsibleSidebar({ className = '' }: CollapsibleSidebarProps) {
  const [isOpen, setIsOpen] = useState(false)
  const location = useLocation()
  const { hasPermission } = useAuth()
  const isDesktop = useIsDesktop()

  // Close sidebar when route changes (for tablet)
  useEffect(() => {
    setIsOpen(false)
  }, [location.pathname])

  // Close sidebar when switching to desktop
  useEffect(() => {
    if (isDesktop) {
      setIsOpen(false)
    }
  }, [isDesktop])

  // Helper to check if current path matches nav item
  const isActive = (path: string): boolean => {
    if (path === '/') {
      return location.pathname === '/'
    }
    return location.pathname.startsWith(path)
  }

  // Filter nav items by permission
  const visibleNavItems = navItems.filter(item => {
    if (!item.permission) return true
    return hasPermission(item.permission)
  })

  return (
    <>
      {/* Toggle Button - visible on tablet only (hidden on mobile and desktop) */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={`
          fixed top-4 left-4 z-50 p-2.5 rounded-lg
          bg-slate-800 border border-slate-700
          text-gray-300 hover:text-white hover:bg-slate-700
          transition-colors duration-200
          min-w-[44px] min-h-[44px]
          hidden sm:flex lg:hidden items-center justify-center
        `}
        aria-label={isOpen ? 'Close navigation menu' : 'Open navigation menu'}
        aria-expanded={isOpen}
        aria-controls="sidebar-nav"
      >
        {isOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
      </button>

      {/* Backdrop Overlay - only shows on tablet when sidebar is open */}
      {isOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/50 lg:hidden hidden sm:block"
          onClick={() => setIsOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Sidebar */}
      <aside
        id="sidebar-nav"
        className={`
          fixed top-0 left-0 z-40 h-full
          bg-slate-900 border-r border-slate-700
          w-64 transform transition-transform duration-300 ease-in-out
          ${/* Mobile: always hidden (use bottom nav) */ ''}
          hidden sm:block
          ${/* Tablet: slide in/out based on isOpen */ ''}
          ${isOpen ? 'translate-x-0' : '-translate-x-full'}
          ${/* Desktop: always visible, fixed position */ ''}
          lg:translate-x-0
          ${className}
        `}
        aria-label="Main navigation"
      >
        <div className="flex flex-col h-full">
          {/* Logo Header - Links to Dashboard */}
          <Link
            to="/"
            className="flex items-center h-16 px-4 border-b border-slate-700 hover:bg-slate-800/50 transition-colors"
            onClick={() => setIsOpen(false)}
          >
            <img
              src={logoImg}
              alt="Jutsu Trading Logo"
              className="w-8 h-8 object-contain"
            />
            <span className="ml-3 text-lg font-bold text-white">Jutsu Trader</span>
          </Link>

          {/* Navigation Links */}
          <nav className="flex-1 overflow-y-auto p-4">
            <ul className="space-y-1">
              {visibleNavItems.map(({ path, icon: Icon, label }) => {
                const active = isActive(path)
                return (
                  <li key={path}>
                    <NavLink
                      to={path}
                      onClick={() => setIsOpen(false)}
                      className={`
                        flex items-center gap-3 px-4 py-3 rounded-lg
                        transition-colors duration-200
                        min-h-[44px]
                        ${active
                          ? 'bg-blue-600 text-white'
                          : 'text-gray-300 hover:bg-slate-800 hover:text-white'
                        }
                      `}
                      aria-current={active ? 'page' : undefined}
                    >
                      <Icon className="w-5 h-5 flex-shrink-0" />
                      <span className="truncate">{label}</span>
                    </NavLink>
                  </li>
                )
              })}
            </ul>
          </nav>

          {/* Footer - Version info */}
          <div className="p-4 border-t border-slate-700">
            <div className="text-xs text-gray-500 text-center">
              Responsive UI v2
            </div>
          </div>
        </div>
      </aside>
    </>
  )
}

export default CollapsibleSidebar
