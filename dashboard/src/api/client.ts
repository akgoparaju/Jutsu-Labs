import axios from 'axios'

// API base URL - uses Vite proxy in development
const API_BASE = '/api'

// Token key must match AuthContext
const TOKEN_KEY = 'jutsu_auth_token'

// Create axios instance
export const api = axios.create({
  baseURL: API_BASE,
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Add request interceptor to include JWT token
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem(TOKEN_KEY)
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

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
  strategy_id?: string
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
  max_drawdown?: number
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
    strategy_id?: string
  }) => api.get<TradeListResponse>('/trades', { params }),
  getTrade: (id: number) => api.get<TradeRecord>(`/trades/${id}`),
  getStats: (params?: { mode?: string; start_date?: string; end_date?: string; strategy_id?: string }) =>
    api.get('/trades/summary/stats', { params }),
  exportCsv: (params?: {
    symbol?: string
    mode?: string
    action?: string
    start_date?: string
    end_date?: string
    strategy_id?: string
  }) => api.get('/trades/export', { params, responseType: 'blob' }),
  // Trade execution (Jutsu Trader)
  executeTrade: (data: ExecuteTradeRequest) =>
    api.post<ExecuteTradeResponse>('/trades/execute', data),
}

export const performanceApi = {
  getPerformance: (params?: { mode?: string; days?: number; start_date?: string; strategy_id?: string }) =>
    api.get<PerformanceResponse>('/performance', { params }),
  getEquityCurve: (params?: { mode?: string; days?: number; start_date?: string; strategy_id?: string }) =>
    api.get('/performance/equity-curve', { params }),
  getDrawdown: (params?: { mode?: string; strategy_id?: string }) =>
    api.get('/performance/drawdown', { params }),
  getRegimeBreakdown: (params?: { mode?: string; days?: number; start_date?: string; strategy_id?: string }) =>
    api.get('/performance/regime-breakdown', { params }),
}

// =============================================================================
// Performance API v2 Types (Pre-computed Daily Performance)
// Uses daily_performance table for fast, consistent KPI retrieval
// Reference: claudedocs/eod_daily_performance_architecture.md
// =============================================================================

export interface BaselineData {
  symbol: string
  total_equity: number
  daily_return?: number
  cumulative_return?: number
  sharpe_ratio?: number
  max_drawdown?: number
}

export interface DailyPerformanceData {
  trading_date: string
  total_equity: number
  cash?: number
  positions_value?: number
  daily_return: number
  cumulative_return: number

  // KPI metrics
  sharpe_ratio?: number
  sortino_ratio?: number
  calmar_ratio?: number
  max_drawdown?: number
  volatility?: number
  cagr?: number

  // Strategy state
  strategy_cell?: string
  trend_state?: string
  vol_state?: string

  // Metadata
  trading_days_count: number
  is_first_day?: boolean
  days_since_previous?: number

  // Optional backward-compatibility fields (for migration from v1)
  // These may not be present in v2 API responses but allow gradual migration
  timestamp?: string  // Alias for trading_date (v1 used timestamp)
  baseline_value?: number  // Current baseline total equity (from daily endpoint baseline)
  baseline_return?: number  // Current baseline cumulative return %
  holdings?: HoldingInfo[]  // Position breakdown (not in v2, kept for display compatibility)
  cash_weight_pct?: number  // Cash as % of portfolio
  drawdown?: number  // Per-day drawdown (v2 only has max_drawdown)
  total_trades?: number  // Cumulative trade count
  win_rate?: number  // Win rate %
  winning_trades?: number  // Count of winning trades
  losing_trades?: number  // Count of losing trades
  mode?: string  // Trading mode (v1 included this per-snapshot)
}

export interface DailyPerformanceResponse {
  strategy_id: string
  mode: string
  data: DailyPerformanceData
  baseline?: BaselineData
  
  // Fallback indicators
  is_finalized: boolean
  data_as_of: string
  finalized_at?: string
}

export interface DailyPerformanceHistoryResponse {
  strategy_id: string
  mode: string
  count: number
  history: DailyPerformanceData[]
  baseline_symbol?: string
}

export interface PerformanceComparisonItem {
  strategy_id: string
  display_name: string
  data: DailyPerformanceData
  is_finalized: boolean
  data_as_of: string
}

export interface PerformanceComparisonResponse {
  strategies: PerformanceComparisonItem[]
  baseline?: BaselineData
  comparison_date: string
}

export interface EODStatusResponse {
  date: string
  finalized: boolean
  status: string
  started_at?: string
  completed_at?: string
  duration_seconds?: number
  error?: string
  progress_pct?: number
}

/**
 * Performance API v2 - Uses pre-computed daily_performance table
 * 
 * Benefits over v1:
 * - Pre-computed KPIs (Sharpe, Sortino, Calmar, CAGR)
 * - Consistent calculations across all displays
 * - Automatic fallback to previous day if today not finalized
 * - Baseline (QQQ) comparison included
 * 
 * @deprecated v1 performanceApi will be sunset on 2026-03-24
 */
export const performanceApiV2 = {
  /**
   * Get daily performance metrics for a strategy
   * Returns pre-computed KPIs with fallback to previous day if today not yet finalized
   */
  getDaily: (
    strategyId: string,
    params?: { mode?: string; baseline_symbol?: string }
  ) =>
    api.get<DailyPerformanceResponse>(`/v2/performance/${strategyId}/daily`, { params }),

  /**
   * Get historical daily performance metrics
   * Returns up to `days` records in descending date order
   */
  getHistory: (
    strategyId: string,
    params?: { mode?: string; days?: number; baseline_symbol?: string }
  ) =>
    api.get<DailyPerformanceHistoryResponse>(
      `/v2/performance/${strategyId}/daily/history`,
      { params }
    ),

  /**
   * Compare daily performance across multiple strategies
   */
  getComparison: (params?: {
    strategy_ids?: string[]
    mode?: string
    baseline_symbol?: string
  }) =>
    api.get<PerformanceComparisonResponse>('/v2/performance/comparison', { params }),

  /**
   * Get EOD finalization status for a specific date
   */
  getEodStatus: (date: string) =>
    api.get<EODStatusResponse>(`/v2/performance/eod-status/${date}`),

  /**
   * Get EOD finalization status for today
   */
  getEodStatusToday: () =>
    api.get<EODStatusResponse>('/v2/performance/eod-status/today'),
}

export const configApi = {
  getConfig: () => api.get<ConfigResponse>('/config'),
  updateConfig: (data: { parameter_name: string; new_value: any; reason?: string; strategy_id?: string }) =>
    api.put('/config', data),
  resetParameter: (name: string, strategy_id?: string) =>
    api.delete(`/config/${name}`, { params: strategy_id ? { strategy_id } : undefined }),
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

// User Management Types
export interface UserInfo {
  id: number
  username: string
  email: string | null
  role: string
  is_active: boolean
  created_at: string
  last_login: string | null
}

export interface UsersListResponse {
  users: UserInfo[]
  total: number
}

export interface InvitationInfo {
  id: number
  email: string
  role: string
  token: string
  expires_at: string
  created_at: string
  accepted: boolean
  accepted_at: string | null
  invited_by_username: string
}

export interface InvitationsListResponse {
  invitations: InvitationInfo[]
  total: number
}

export interface CreateInvitationRequest {
  email: string
  role?: string
}

export interface CreateInvitationResponse {
  message: string
  invitation_id: number
  email: string
  role: string
  expires_at: string
  invitation_link: string
}

export interface UpdateRoleRequest {
  role: string
}

export interface AcceptInvitationRequest {
  username: string
  password: string
  email?: string
}

export interface AcceptInvitationResponse {
  success: boolean
  username: string
  role: string
  message: string
}

export interface ValidateInvitationResponse {
  valid: boolean
  email: string | null
  role: string
  expires_at: string
}

// Backtest Types
export interface BacktestSummary {
  strategy_name?: string
  start_date?: string
  end_date?: string
  initial_capital?: number
  total_return?: number
  annualized_return?: number
  sharpe_ratio?: number
  max_drawdown?: number
  alpha?: number
  baseline_ticker?: string
  baseline_total_return?: number
  baseline_cagr?: number
  baseline_sharpe_ratio?: number
  baseline_max_drawdown?: number
}

export interface BacktestDataPoint {
  date: string
  portfolio?: number
  baseline?: number
  buyhold?: number
  regime?: string
  trend?: string
  vol?: string
}

export interface BacktestPeriodMetrics {
  start_date?: string
  end_date?: string
  days?: number
  period_return?: number
  annualized_return?: number
  baseline_return?: number
  baseline_annualized?: number
  alpha?: number
}

export interface BacktestRegimePerformance {
  cell?: number
  regime: string
  trend?: string
  vol?: string
  total_return: number
  annualized_return?: number
  baseline_annualized?: number
  days: number
  pct_of_time: number
}

export interface BacktestDataResponse {
  summary: BacktestSummary
  timeseries: BacktestDataPoint[]
  period_metrics?: BacktestPeriodMetrics
  total_data_points: number
  filtered_data_points: number
}

export interface BacktestRegimeResponse {
  regimes: BacktestRegimePerformance[]
  start_date?: string
  end_date?: string
}

export interface BacktestConfigResponse {
  config: Record<string, unknown>
  file_path: string
  strategy_name?: string
}

// Backtest API
export const backtestApi = {
  getStrategies: () => api.get<BacktestStrategiesResponse>('/backtest/strategies'),
  getData: (params?: { start_date?: string; end_date?: string; strategy_id?: string }) =>
    api.get<BacktestDataResponse>('/backtest/data', { params }),
  getConfig: (params?: { strategy_id?: string }) =>
    api.get<BacktestConfigResponse>('/backtest/config', { params }),
  getRegimeBreakdown: (params?: { start_date?: string; end_date?: string; strategy_id?: string }) =>
    api.get<BacktestRegimeResponse>('/backtest/regime-breakdown', { params }),
}

// Strategy Types
export interface StrategyInfo {
  id: string
  display_name: string
  strategy_class: string
  is_primary: boolean
  is_active: boolean
  paper_trading: boolean
  description?: string
  config_file?: string
}

export interface StrategyStatus {
  display_name: string
  is_primary: boolean
  paper_trading: boolean
  last_run?: string
  vol_state?: number | string
  trend_state?: string
  account_equity?: number
  position_count?: number
}

export interface StrategiesListResponse {
  strategies: StrategyInfo[]
  primary_id?: string
  execution_order: string[]
  settings: {
    isolate_failures: boolean
    execution_timeout: number
    shared_data_fetch: boolean
  }
}

export interface StrategiesStatusResponse {
  strategies: Record<string, StrategyStatus>
  primary_id?: string
}

export interface BacktestStrategyInfo {
  strategy_id: string
  strategy_name: string
  file_path: string
  last_modified: number
}

export interface BacktestStrategiesResponse {
  strategies: BacktestStrategyInfo[]
  count: number
}

// Strategies API
export const strategiesApi = {
  getStrategies: (params?: { active_only?: boolean }) =>
    api.get<StrategiesListResponse>('/strategies', { params }),
  getStatus: () => api.get<StrategiesStatusResponse>('/strategies/status'),
  getStrategy: (strategyId: string) =>
    api.get<StrategyInfo>(`/strategies/${strategyId}`),
  getStrategyState: (strategyId: string) =>
    api.get(`/strategies/${strategyId}/state`),
  getPrimaryState: () => api.get('/strategies/primary/state'),
}

// User Management API
export const usersApi = {
  // Admin-only endpoints (under /users)
  listUsers: () => api.get<UsersListResponse>('/users'),
  listInvitations: () => api.get<InvitationsListResponse>('/users/invitations'),
  createInvitation: (data: CreateInvitationRequest) =>
    api.post<CreateInvitationResponse>('/users/invite', data),
  updateRole: (userId: number, data: UpdateRoleRequest) =>
    api.put(`/users/${userId}`, data),
  deactivateUser: (userId: number) =>
    api.delete(`/users/${userId}`),
  revokeInvitation: (invitationId: number) =>
    api.delete(`/users/invitations/${invitationId}`),
  // Public invitation endpoints (under /invitations - no auth required)
  validateInvitation: (token: string) =>
    api.get<ValidateInvitationResponse>(`/invitations/${token}`),
  acceptInvitation: (token: string, data: AcceptInvitationRequest) =>
    api.post<AcceptInvitationResponse>(`/invitations/${token}/accept`, data),
}
