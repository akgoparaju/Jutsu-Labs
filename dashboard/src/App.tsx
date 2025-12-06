import { Routes, Route } from 'react-router-dom'
import { AuthProvider } from './contexts/AuthContext'
import ProtectedRoute from './components/ProtectedRoute'
import Layout from './components/Layout'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Trades from './pages/Trades'
import Performance from './pages/Performance'
import Config from './pages/Config'
import DecisionTree from './pages/DecisionTree'

function App() {
  return (
    <AuthProvider>
      <Routes>
        {/* Public route: Login */}
        <Route path="/login" element={<Login />} />

        {/* Protected routes: Dashboard and sub-pages */}
        <Route element={<ProtectedRoute />}>
          <Route path="/" element={<Layout />}>
            <Route index element={<Dashboard />} />
            <Route path="decision-tree" element={<DecisionTree />} />
            <Route path="trades" element={<Trades />} />
            <Route path="performance" element={<Performance />} />
            <Route path="config" element={<Config />} />
          </Route>
        </Route>
      </Routes>
    </AuthProvider>
  )
}

export default App
