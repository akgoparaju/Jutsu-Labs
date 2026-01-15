import { Routes, Route } from 'react-router-dom'
import { AuthProvider } from './contexts/AuthContext'
import ProtectedRoute from './components/ProtectedRoute'
import RequirePermission from './components/RequirePermission'
import Layout from './components/Layout'
import Login from './pages/Login'
import AcceptInvitation from './pages/AcceptInvitation'
import Dashboard from './pages/Dashboard'
import Trades from './pages/Trades'
import Performance from './pages/Performance'
import Config from './pages/Config'
import DecisionTree from './pages/DecisionTree'
import Settings from './pages/Settings'

// V2 Responsive UI imports
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

        {/* Protected routes: Dashboard and sub-pages */}
        <Route element={<ProtectedRoute />}>
          <Route path="/" element={<Layout />}>
            <Route index element={<Dashboard />} />
            <Route path="decision-tree" element={<DecisionTree />} />
            <Route path="trades" element={<Trades />} />
            <Route path="performance" element={<Performance />} />
            <Route path="config" element={
              <RequirePermission permission="config:write" redirectTo="/">
                <Config />
              </RequirePermission>
            } />
            <Route path="settings" element={<Settings />} />
          </Route>

          {/* V2 Responsive UI routes (parallel development) */}
          <Route path="/v2" element={<ResponsiveLayout />}>
            <Route index element={<DashboardV2 />} />
            <Route path="decision-tree" element={<DecisionTreeV2 />} />
            <Route path="trades" element={<TradesV2 />} />
            <Route path="performance" element={<PerformanceV2 />} />
            <Route path="config" element={
              <RequirePermission permission="config:write" redirectTo="/v2">
                <ConfigV2 />
              </RequirePermission>
            } />
            <Route path="settings" element={<SettingsV2 />} />
            <Route path="more" element={<MoreV2 />} />
          </Route>
        </Route>
      </Routes>
    </AuthProvider>
  )
}

export default App
