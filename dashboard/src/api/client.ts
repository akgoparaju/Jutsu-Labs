import axios from 'axios'

// API base URL - uses Vite proxy in development
const API_BASE = '/api'

// Create axios instance
export const api = axios.create({
  baseURL: API_BASE,
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Types
export interface RegimeInfo {
  cell: number
  trend_state: string
  vol_state: string
  t_norm?: number
  z_score?: number
}

export interface PositionInfo {
  symbol: string
  quantity: number
  avg_cost?: number
  market_value?: number
  unrealized_pnl?: number
  weight_pct?: number
}

export interface PortfolioInfo {
  total_equity: number
  cash?: number
  positions_value?: number
  positions: PositionInfo[]
}

export interface SystemStatus {
  mode: string
  is_running: boolean
  last_execution?: string
  next_execution?: string
  regime?: RegimeInfo
  portfolio?: PortfolioInfo
  uptime_seconds?: number
  error?: string
}

export interface TradeRecord {
  id: number
  symbol: string
  timestamp: string
  action: string
  quantity: number
  target_price: number
  fill_price?: number
  fill_value?: number
  slippage_pct?: number
  schwab_order_id?: string
  strategy_cell?: number
  trend_state?: string
  vol_state?: string
  t_norm?: number
  z_score?: number
  reason?: string
  mode: string
}

export interface TradeListResponse {
  trades: TradeRecord[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

// Trade Execution Types (Jutsu Trader)
export interface ExecuteTradeRequest {
  symbol: string
  action: 'BUY' | 'SELL'
  quantity: number
  reason?: string
}

export interface ExecuteTradeResponse {
  success: boolean
  trade_id?: number
  symbol: string
  action: string
  quantity: number
  target_price: number
  fill_price?: number
  fill_value?: number
  slippage_pct?: number
  message: string
  timestamp: string
}

export interface HoldingInfo {
  symbol: string
  quantity: number
  value: number
  weight_pct: number
}

export interface PerformanceMetrics {
  total_equity: number
  holdings?: HoldingInfo[]
  cash?: number
  cash_weight_pct?: number
  daily_return?: number
  cumulative_return?: number
  drawdown?: number
  high_water_mark?: number
  sharpe_ratio?: number
  win_rate?: number
  total_trades: number
  winning_trades: number
  losing_trades: number
}

export interface SnapshotPositionInfo {
  symbol: string
  quantity: number
  value: number
}

export interface PerformanceSnapshot {
  timestamp: string
  total_equity: number
  cash?: number
  positions_value?: number
  daily_return?: number
  cumulative_return?: number
  drawdown?: number
  strategy_cell?: number
  trend_state?: string
  vol_state?: string
  positions?: SnapshotPositionInfo[]  // Position breakdown
  baseline_value?: number  // QQQ buy-and-hold portfolio value
  baseline_return?: number  // QQQ buy-and-hold cumulative return %
  mode: string
}

export interface PerformanceResponse {
  current: PerformanceMetrics
  history: PerformanceSnapshot[]
  mode: string
}

export interface ConfigParameter {
  name: string
  value: any
  original_value?: any
  is_overridden: boolean
  constraints?: {
    min_value?: number
    max_value?: number
    allowed_values?: any[]
    value_type: string
  }
  description?: string
}

export interface ConfigResponse {
  strategy_name: string
  parameters: ConfigParameter[]
  active_overrides: number
  last_modified?: string
}

export interface ControlResponse {
  success: boolean
  action: string
  previous_state: string
  new_state: string
  message: string
  timestamp: string
}

// Scheduler Types
export interface SchedulerStatus {
  enabled: boolean
  execution_time: string
  execution_time_est: string
  next_run: string | null
  last_run: string | null
  last_run_status: 'success' | 'failed' | 'skipped' | null
  last_error: string | null
  run_count: number
  is_running: boolean
  valid_execution_times: string[]
}

export interface IndicatorValue {
  name: string
  value: number
  signal?: string
  description?: string
}

export interface IndicatorsResponse {
  timestamp: string
  indicators: IndicatorValue[]
  symbol: string
  target_allocation?: {
    TQQQ: number
    QQQ: number
    PSQ: number
    TMF: number
    TMV: number
    CASH: number
  }
}

// API Functions
export const statusApi = {
  getStatus: () => api.get<SystemStatus>('/status'),
  getHealth: () => api.get('/status/health'),
  getRegime: () => api.get<RegimeInfo>('/status/regime'),
}

export const tradesApi = {
  getTrades: (params?: {
    page?: number
    page_size?: number
    symbol?: string
    mode?: string
    action?: string
    start_date?: string
    end_date?: string
  }) => api.get<TradeListResponse>('/trades', { params }),
  getTrade: (id: number) => api.get<TradeRecord>(`/trades/${id}`),
  getStats: (params?: { mode?: string; start_date?: string; end_date?: string }) =>
    api.get('/trades/summary/stats', { params }),
  exportCsv: (params?: {
    symbol?: string
    mode?: string
    action?: string
    start_date?: string
    end_date?: string
  }) => api.get('/trades/export', { params, responseType: 'blob' }),
  // Trade execution (Jutsu Trader)
  executeTrade: (data: ExecuteTradeRequest) =>
    api.post<ExecuteTradeResponse>('/trades/execute', data),
}

export const performanceApi = {
  getPerformance: (params?: { mode?: string; days?: number }) =>
    api.get<PerformanceResponse>('/performance', { params }),
  getEquityCurve: (params?: { mode?: string; days?: number }) =>
    api.get('/performance/equity-curve', { params }),
  getDrawdown: (params?: { mode?: string }) =>
    api.get('/performance/drawdown', { params }),
  getRegimeBreakdown: (params?: { mode?: string }) =>
    api.get('/performance/regime-breakdown', { params }),
}

export const configApi = {
  getConfig: () => api.get<ConfigResponse>('/config'),
  updateConfig: (data: { parameter_name: string; new_value: any; reason?: string }) =>
    api.put('/config', data),
  resetParameter: (name: string) => api.delete(`/config/${name}`),
}

export const controlApi = {
  start: (data: { action: string; mode?: string; confirm?: boolean }) =>
    api.post<ControlResponse>('/control/start', data),
  stop: (data: { action: string }) =>
    api.post<ControlResponse>('/control/stop', data),
  restart: (data: { action: string; mode?: string; confirm?: boolean }) =>
    api.post<ControlResponse>('/control/restart', data),
  getState: () => api.get('/control/state'),
  switchMode: (data: { action: string; mode: string; confirm?: boolean }) =>
    api.post<ControlResponse>('/control/mode', data),
  // Scheduler endpoints
  getSchedulerStatus: () => api.get<SchedulerStatus>('/control/scheduler'),
  enableScheduler: () => api.post<ControlResponse>('/control/scheduler/enable'),
  disableScheduler: () => api.post<ControlResponse>('/control/scheduler/disable'),
  triggerScheduler: () => api.post<ControlResponse>('/control/scheduler/trigger'),
}

export const indicatorsApi = {
  getIndicators: () => api.get<IndicatorsResponse>('/indicators'),
  getDescriptions: () => api.get('/indicators/descriptions'),
}

// Schwab Authentication Types
export interface SchwabAuthStatus {
  authenticated: boolean
  token_exists: boolean
  token_valid: boolean
  token_age_days?: number
  expires_in_days?: number
  message: string
  callback_url?: string
}

export interface SchwabAuthInitiate {
  authorization_url: string
  callback_url: string
  state: string
  instructions: string
}

export interface SchwabAuthCallback {
  callback_url: string
}

export interface SchwabAuthCallbackResponse {
  success: boolean
  message: string
  token_created: boolean
}

// Schwab Authentication API
export const schwabAuthApi = {
  getStatus: () => api.get<SchwabAuthStatus>('/schwab/status'),
  initiate: () => api.post<SchwabAuthInitiate>('/schwab/initiate'),
  callback: (data: SchwabAuthCallback) =>
    api.post<SchwabAuthCallbackResponse>('/schwab/callback', data),
  deleteToken: () => api.delete('/schwab/token'),
}
