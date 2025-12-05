import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Trades from './pages/Trades'
import Performance from './pages/Performance'
import Config from './pages/Config'
import DecisionTree from './pages/DecisionTree'

function App() {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="decision-tree" element={<DecisionTree />} />
        <Route path="trades" element={<Trades />} />
        <Route path="performance" element={<Performance />} />
        <Route path="config" element={<Config />} />
      </Route>
    </Routes>
  )
}

export default App
