/**
 * MobileBottomNav - Bottom Tab Navigation for Mobile Devices
 *
 * Displays a fixed bottom navigation bar on mobile devices (<640px).
 * Features:
 * - 5 primary navigation items with icons
 * - Active state highlighting
 * - Safe-area-inset-bottom padding for notched devices
 * - 44px minimum touch targets
 * - Hidden on sm breakpoint and above
 *
 * @version 1.0.0
 * @part Responsive UI - Phase 2.2
 */

import { NavLink, useLocation } from 'react-router-dom'
import {
  LayoutDashboard,
  GitBranch,
  TrendingUp,
  History,
  MoreHorizontal,
} from 'lucide-react'

interface NavItem {
  path: string
  icon: React.ComponentType<{ className?: string }>
  label: string
}

const navItems: NavItem[] = [
  { path: '/v2', icon: LayoutDashboard, label: 'Dashboard' },
  { path: '/v2/decision-tree', icon: GitBranch, label: 'Tree' },
  { path: '/v2/performance', icon: TrendingUp, label: 'Performance' },
  { path: '/v2/trades', icon: History, label: 'Trades' },
  { path: '/v2/more', icon: MoreHorizontal, label: 'More' },
]

export function MobileBottomNav() {
  const location = useLocation()

  // Helper to check if current path matches nav item
  const isActive = (path: string): boolean => {
    if (path === '/v2') {
      return location.pathname === '/v2'
    }
    return location.pathname.startsWith(path)
  }

  return (
    <nav
      className="fixed bottom-0 left-0 right-0 z-50 bg-slate-900 border-t border-slate-700 sm:hidden"
      aria-label="Mobile navigation"
    >
      <div
        className="flex justify-around items-center h-16 px-1"
        style={{ paddingBottom: 'env(safe-area-inset-bottom, 0px)' }}
      >
        {navItems.map(({ path, icon: Icon, label }) => {
          const active = isActive(path)
          return (
            <NavLink
              key={path}
              to={path}
              className={`
                flex flex-col items-center justify-center
                min-w-[56px] min-h-[44px] px-2 py-1.5 rounded-lg
                transition-colors duration-200
                ${active
                  ? 'text-blue-400 bg-blue-400/10'
                  : 'text-gray-400 hover:text-gray-200 active:bg-slate-800'
                }
              `}
              aria-current={active ? 'page' : undefined}
            >
              <Icon className="w-5 h-5 mb-0.5" />
              <span className="text-[10px] font-medium leading-tight">{label}</span>
            </NavLink>
          )
        })}
      </div>
    </nav>
  )
}

export default MobileBottomNav
