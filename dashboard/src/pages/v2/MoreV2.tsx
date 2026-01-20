/**
 * MoreV2 - Mobile "More" Menu Page
 *
 * On mobile devices, this page provides access to secondary navigation items
 * that don't fit in the 5-item bottom navigation bar.
 *
 * @version 1.0.0
 * @part Responsive UI - Phase 2
 */

import { NavLink } from 'react-router-dom'
import { Settings, Shield, BarChart3 } from 'lucide-react'
import { ResponsiveCard, ResponsiveText } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'

interface MenuItem {
  path: string
  icon: React.ComponentType<{ className?: string }>
  label: string
  description: string
  permission?: string
}

const menuItems: MenuItem[] = [
  {
    path: '/config',
    icon: Settings,
    label: 'Configuration',
    description: 'Trading strategy and engine settings',
    permission: 'config:write',
  },
  {
    path: '/backtest',
    icon: BarChart3,
    label: 'Backtest Results',
    description: 'View golden backtest performance and metrics',
  },
  {
    path: '/settings',
    icon: Shield,
    label: 'Account Settings',
    description: 'Security, 2FA, and passkey management',
  },
]

function MoreV2() {
  const { hasPermission } = useAuth()

  const visibleItems = menuItems.filter(item => {
    if (!item.permission) return true
    return hasPermission(item.permission)
  })

  return (
    <div className="space-y-4 sm:space-y-6">
      <ResponsiveText variant="h1" as="h1">
        More
      </ResponsiveText>

      <div className="space-y-3">
        {visibleItems.map(({ path, icon: Icon, label, description }) => (
          <NavLink key={path} to={path}>
            <ResponsiveCard padding="md" className="hover:bg-slate-700/50 transition-colors">
              <div className="flex items-center gap-4">
                <div className="flex items-center justify-center w-12 h-12 rounded-lg bg-slate-700">
                  <Icon className="w-6 h-6 text-blue-400" />
                </div>
                <div>
                  <ResponsiveText variant="h3" as="h3">
                    {label}
                  </ResponsiveText>
                  <ResponsiveText variant="small" className="text-gray-400">
                    {description}
                  </ResponsiveText>
                </div>
              </div>
            </ResponsiveCard>
          </NavLink>
        ))}
      </div>

      {visibleItems.length === 0 && (
        <ResponsiveCard padding="md">
          <ResponsiveText variant="body" className="text-gray-400 text-center">
            No additional options available.
          </ResponsiveText>
        </ResponsiveCard>
      )}
    </div>
  )
}

export default MoreV2
