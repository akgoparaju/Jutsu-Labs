import { Routes, Route } from 'react-router-dom'
import { AuthProvider } from './contexts/AuthContext'
import ProtectedRoute from './components/ProtectedRoute'
import RequirePermission from './components/RequirePermission'
import Layout from './components/Layout'
import Login from './pages/Login'
import AcceptInvitation from './pages/AcceptInvitation'

// Legacy V1 imports (will be removed after verification period)
import {
  Dashboard,
  DecisionTree,
  Trades,
  Performance,
  Config,
  Settings,
} from './pages/legacy'

// V2 Responsive UI imports (now default)
import ResponsiveLayout from './layouts/ResponsiveLayout'
import {
  DashboardV2,
  DecisionTreeV2,
  PerformanceV2,
  TradesV2,
  ConfigV2,
  SettingsV2,
  MoreV2,
} from './pages/v2'

function App() {
  return (
    <AuthProvider>
      <Routes>
        {/* Public routes: Login and Accept Invitation */}
        <Route path="/login" element={<Login />} />
        <Route path="/accept-invitation" element={<AcceptInvitation />} />

        {/* Protected routes */}
        <Route element={<ProtectedRoute />}>
          {/* Default routes: V2 Responsive UI */}
          <Route path="/" element={<ResponsiveLayout />}>
            <Route index element={<DashboardV2 />} />
            <Route path="decision-tree" element={<DecisionTreeV2 />} />
            <Route path="trades" element={<TradesV2 />} />
            <Route path="performance" element={<PerformanceV2 />} />
            <Route path="config" element={
              <RequirePermission permission="config:write" redirectTo="/">
                <ConfigV2 />
              </RequirePermission>
            } />
            <Route path="settings" element={<SettingsV2 />} />
            <Route path="more" element={<MoreV2 />} />
          </Route>

          {/* Legacy V1 routes (will be removed after verification period) */}
          <Route path="/legacy" element={<Layout />}>
            <Route index element={<Dashboard />} />
            <Route path="decision-tree" element={<DecisionTree />} />
            <Route path="trades" element={<Trades />} />
            <Route path="performance" element={<Performance />} />
            <Route path="config" element={
              <RequirePermission permission="config:write" redirectTo="/legacy">
                <Config />
              </RequirePermission>
            } />
            <Route path="settings" element={<Settings />} />
          </Route>
        </Route>
      </Routes>
    </AuthProvider>
  )
}

export default App
