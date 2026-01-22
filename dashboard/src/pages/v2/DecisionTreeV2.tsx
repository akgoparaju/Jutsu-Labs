/**
 * DecisionTreeV2 - Responsive Decision Tree Page
 *
 * Displays the complete decision tree logic for cell assignment:
 * - Stage 1: Trend Classification (Kalman + SMA)
 * - Stage 2: Volatility Classification (Z-Score + Vol-Crush)
 * - Stage 3: Cell Assignment (6-Cell Matrix)
 * - Stage 4: Treasury Overlay
 * - Final Allocation Table
 *
 * @version 2.0.0
 * @part Responsive UI - Phase 4
 */

import { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { indicatorsApi, backtestApi, IndicatorsResponse, BacktestConfigResponse } from '../../api/client'
import { useStrategy } from '../../contexts/StrategyContext'
import {
  GitBranch,
  TrendingUp,
  TrendingDown,
  Activity,
  Zap,
  Shield,
  ArrowRight,
  CheckCircle2,
  Circle,
  ChevronDown,
} from 'lucide-react'
import { ResponsiveCard, ResponsiveText } from '../../components/ui'
import { useIsMobileOrSmaller } from '../../hooks/useMediaQuery'

function DecisionTreeV2() {
  const isMobile = useIsMobileOrSmaller()
  const [searchParams] = useSearchParams()
  const { strategies: availableStrategies } = useStrategy()

  // Get selected strategies from URL params (same pattern as Dashboard)
  const selectedStrategies = searchParams.get('strategies')?.split(',').filter(Boolean) || []

  // State for selected strategy in Decision Tree view
  const [selectedStrategy, setSelectedStrategy] = useState<string>('')

  // Initialize selected strategy from URL params or use first available
  useEffect(() => {
    if (selectedStrategies.length > 0 && !selectedStrategies.includes(selectedStrategy)) {
      setSelectedStrategy(selectedStrategies[0])
    } else if (selectedStrategies.length === 0 && availableStrategies.length > 0 && !selectedStrategy) {
      setSelectedStrategy(availableStrategies[0].id)
    }
  }, [selectedStrategies, availableStrategies, selectedStrategy])

  // Fetch config for thresholds using backtest config API (supports strategy_id)
  const { data: backtestConfig, isLoading: configLoading } = useQuery<BacktestConfigResponse>({
    queryKey: ['backtest-config', selectedStrategy],
    queryFn: async () => {
      const response = await backtestApi.getConfig({ strategy_id: selectedStrategy })
      return response.data
    },
    enabled: !!selectedStrategy,
    refetchInterval: 30000,
  })

  // Convert backtest config to our config format
  // The YAML structure has parameters nested under strategy.parameters
  const strategyParams = (backtestConfig?.config as Record<string, unknown>)?.strategy as Record<string, unknown> | undefined
  const configParams = strategyParams?.parameters as Record<string, unknown> | undefined

  const config = backtestConfig ? {
    strategy_name: backtestConfig.strategy_name || selectedStrategy,
    parameters: Object.entries(configParams || {}).map(([name, value]) => ({
      name,
      value,
      is_overridden: false,
    })),
    active_overrides: 0,
  } : undefined

  // Fetch current indicators
  const { data: indicators, isLoading: indicatorsLoading } = useQuery<IndicatorsResponse>({
    queryKey: ['indicators'],
    queryFn: async () => {
      const response = await indicatorsApi.getIndicators()
      return response.data
    },
    refetchInterval: 5000,
  })

  // Helper to get config parameter value
  const getParam = (name: string): unknown => {
    const param = config?.parameters?.find(p => p.name === name)
    return param?.value
  }

  // Helper to get indicator value
  const getIndicator = (name: string) =>
    indicators?.indicators?.find(i => i.name === name)

  // Current values
  const tNorm = getIndicator('t_norm')?.value as number | undefined
  const zScore = getIndicator('z_score')?.value as number | undefined
  const smaFast = getIndicator('sma_fast')?.value as number | undefined
  const smaSlow = getIndicator('sma_slow')?.value as number | undefined
  const trendState = getIndicator('trend_state')?.signal
  const volState = getIndicator('vol_state')?.signal
  const currentCell = getIndicator('current_cell')?.value as number | undefined
  const volCrushTriggered = getIndicator('vol_crush_triggered')?.value === 1

  // Config thresholds
  const tNormBullThresh = getParam('t_norm_bull_thresh') as number ?? 0.05
  const tNormBearThresh = getParam('t_norm_bear_thresh') as number ?? -0.3
  const smaFastPeriod = getParam('sma_fast') as number ?? 40
  const smaSlowPeriod = getParam('sma_slow') as number ?? 140
  const upperThreshZ = getParam('upper_thresh_z') as number ?? 1.0
  const lowerThreshZ = getParam('lower_thresh_z') as number ?? 0.2
  const volCrushThreshold = getParam('vol_crush_threshold') as number ?? -0.15
  const volCrushLookback = getParam('vol_crush_lookback') as number ?? 5
  const bondSmaFast = getParam('bond_sma_fast') as number ?? 20
  const bondSmaSlow = getParam('bond_sma_slow') as number ?? 60

  // v3.5d Cell 1 Exit Confirmation parameters
  const cell1ExitConfirmationEnabled = getParam('cell1_exit_confirmation_enabled') as boolean ?? false
  const cell1ExitConfirmationDays = getParam('cell1_exit_confirmation_days') as number ?? 2
  const cell1ExitPendingDays = getIndicator('cell1_exit_pending_days')?.value as number | undefined

  // Derived states
  const kalmanSignal = tNorm !== undefined
    ? tNorm > tNormBullThresh ? 'Bull'
      : tNorm < tNormBearThresh ? 'Bear'
        : 'Neutral'
    : 'N/A'

  const smaStructure = smaFast !== undefined && smaSlow !== undefined
    ? smaFast > smaSlow ? 'Bull' : 'Bear'
    : 'N/A'

  const isLoading = configLoading || indicatorsLoading

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500" />
      </div>
    )
  }

  return (
    <div className="space-y-4 sm:space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
        <ResponsiveText variant="h1" as="h1" className="flex items-center gap-2">
          <GitBranch className="w-5 h-5 sm:w-6 sm:h-6 text-purple-400" />
          Cell Decision Tree
        </ResponsiveText>
        <div className="flex items-center gap-3">
          {/* Strategy selector dropdown - always visible */}
          <div className="relative">
            <select
              value={selectedStrategy}
              onChange={(e) => setSelectedStrategy(e.target.value)}
              className="appearance-none bg-slate-700/50 border border-slate-600 rounded-lg px-3 py-1.5 pr-8 text-sm text-gray-200 cursor-pointer hover:border-purple-500/50 focus:outline-none focus:border-purple-500"
            >
              {availableStrategies.map((strategy) => (
                <option key={strategy.id} value={strategy.id}>
                  {strategy.display_name}
                </option>
              ))}
            </select>
            <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
          </div>
        </div>
      </div>

      {/* Decision Flow Visualization */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 sm:gap-6">

        {/* Stage 1: Trend Classification */}
        <ResponsiveCard padding="md">
          <h3 className="text-base sm:text-lg font-semibold mb-3 sm:mb-4 flex items-center gap-2 text-blue-400">
            <span className="bg-blue-500/20 px-2 py-1 rounded text-xs">STAGE 1</span>
            Trend Classification
          </h3>

          {/* Kalman Trend Detector */}
          <div className="mb-4 sm:mb-6">
            <h4 className="text-sm sm:text-md font-medium mb-2 sm:mb-3 text-gray-300">1.1 Kalman Trend Detector</h4>
            <div className="bg-slate-700/50 rounded p-3 sm:p-4 space-y-2">
              <div className="flex items-center gap-2 text-sm">
                <span className="text-gray-400">Input:</span>
                <code className="text-cyan-400 text-xs sm:text-sm">T_norm = {tNorm?.toFixed(4) ?? 'N/A'}</code>
              </div>

              <div className="border-t border-slate-600 my-2" />

              <div className="space-y-1 text-xs sm:text-sm">
                <div className={`flex items-center gap-2 ${kalmanSignal === 'Bull' ? 'text-green-400' : 'text-gray-500'}`}>
                  {kalmanSignal === 'Bull' ? <CheckCircle2 className="w-3 h-3 sm:w-4 sm:h-4 flex-shrink-0" /> : <Circle className="w-3 h-3 sm:w-4 sm:h-4 flex-shrink-0" />}
                  <span className="break-words">T_norm {'>'} <code className="text-yellow-400">{tNormBullThresh}</code> → Bull</span>
                </div>
                <div className={`flex items-center gap-2 ${kalmanSignal === 'Bear' ? 'text-red-400' : 'text-gray-500'}`}>
                  {kalmanSignal === 'Bear' ? <CheckCircle2 className="w-3 h-3 sm:w-4 sm:h-4 flex-shrink-0" /> : <Circle className="w-3 h-3 sm:w-4 sm:h-4 flex-shrink-0" />}
                  <span className="break-words">T_norm {'<'} <code className="text-yellow-400">{tNormBearThresh}</code> → Bear</span>
                </div>
                <div className={`flex items-center gap-2 ${kalmanSignal === 'Neutral' ? 'text-yellow-400' : 'text-gray-500'}`}>
                  {kalmanSignal === 'Neutral' ? <CheckCircle2 className="w-3 h-3 sm:w-4 sm:h-4 flex-shrink-0" /> : <Circle className="w-3 h-3 sm:w-4 sm:h-4 flex-shrink-0" />}
                  <span>Otherwise → Neutral</span>
                </div>
              </div>

              <div className="border-t border-slate-600 my-2" />

              <div className="flex items-center gap-2">
                <span className="text-gray-400 text-sm">Result:</span>
                <span className={`font-bold text-sm sm:text-base ${
                  kalmanSignal === 'Bull' ? 'text-green-400' :
                    kalmanSignal === 'Bear' ? 'text-red-400' : 'text-yellow-400'
                }`}>
                  {kalmanSignal}
                </span>
              </div>
            </div>
          </div>

          {/* SMA Structure */}
          <div className="mb-4 sm:mb-6">
            <h4 className="text-sm sm:text-md font-medium mb-2 sm:mb-3 text-gray-300">1.2 SMA Structure</h4>
            <div className="bg-slate-700/50 rounded p-3 sm:p-4 space-y-2">
              <div className="flex items-center gap-2 text-xs sm:text-sm">
                <span className="text-gray-400">SMA Fast ({smaFastPeriod}d):</span>
                <code className="text-cyan-400">{smaFast?.toFixed(2) ?? 'N/A'}</code>
              </div>
              <div className="flex items-center gap-2 text-xs sm:text-sm">
                <span className="text-gray-400">SMA Slow ({smaSlowPeriod}d):</span>
                <code className="text-cyan-400">{smaSlow?.toFixed(2) ?? 'N/A'}</code>
              </div>

              <div className="border-t border-slate-600 my-2" />

              <div className="space-y-1 text-xs sm:text-sm">
                <div className={`flex items-center gap-2 ${smaStructure === 'Bull' ? 'text-green-400' : 'text-gray-500'}`}>
                  {smaStructure === 'Bull' ? <CheckCircle2 className="w-3 h-3 sm:w-4 sm:h-4 flex-shrink-0" /> : <Circle className="w-3 h-3 sm:w-4 sm:h-4 flex-shrink-0" />}
                  <span>Fast {'>'} Slow → Bull Structure</span>
                </div>
                <div className={`flex items-center gap-2 ${smaStructure === 'Bear' ? 'text-red-400' : 'text-gray-500'}`}>
                  {smaStructure === 'Bear' ? <CheckCircle2 className="w-3 h-3 sm:w-4 sm:h-4 flex-shrink-0" /> : <Circle className="w-3 h-3 sm:w-4 sm:h-4 flex-shrink-0" />}
                  <span>Fast {'<'} Slow → Bear Structure</span>
                </div>
              </div>

              <div className="border-t border-slate-600 my-2" />

              <div className="flex items-center gap-2">
                <span className="text-gray-400 text-sm">Result:</span>
                <span className={`font-bold text-sm sm:text-base ${smaStructure === 'Bull' ? 'text-green-400' : 'text-red-400'}`}>
                  {smaStructure}
                </span>
              </div>
            </div>
          </div>

          {/* Combined Trend */}
          <div>
            <h4 className="text-sm sm:text-md font-medium mb-2 sm:mb-3 text-gray-300">1.3 Combined Trend State</h4>
            <div className="bg-slate-700/50 rounded p-3 sm:p-4">
              {isMobile ? (
                // Mobile: Card view
                <div className="space-y-2">
                  <div className={`p-2 rounded ${kalmanSignal === 'Bull' && smaStructure === 'Bull' ? 'bg-green-500/20' : 'bg-slate-600/30'}`}>
                    <div className="flex justify-between items-center">
                      <span className="text-xs text-gray-400">Bull + Bull</span>
                      <span className="text-green-400 font-bold text-sm">BullStrong</span>
                    </div>
                  </div>
                  <div className={`p-2 rounded ${kalmanSignal === 'Bear' && smaStructure === 'Bear' ? 'bg-red-500/20' : 'bg-slate-600/30'}`}>
                    <div className="flex justify-between items-center">
                      <span className="text-xs text-gray-400">Bear + Bear</span>
                      <span className="text-red-400 font-bold text-sm">BearStrong</span>
                    </div>
                  </div>
                  <div className={`p-2 rounded ${!(kalmanSignal === 'Bull' && smaStructure === 'Bull') && !(kalmanSignal === 'Bear' && smaStructure === 'Bear') ? 'bg-yellow-500/20' : 'bg-slate-600/30'}`}>
                    <div className="flex justify-between items-center">
                      <span className="text-xs text-gray-400">Other combos</span>
                      <span className="text-yellow-400 font-bold text-sm">Sideways</span>
                    </div>
                  </div>
                </div>
              ) : (
                // Desktop: Table view
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-600">
                      <th className="py-2 text-left text-gray-400">Kalman</th>
                      <th className="py-2 text-left text-gray-400">SMA</th>
                      <th className="py-2 text-left text-gray-400">→ Trend</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr className={kalmanSignal === 'Bull' && smaStructure === 'Bull' ? 'bg-green-500/20' : ''}>
                      <td className="py-1">Bull</td>
                      <td className="py-1">Bull</td>
                      <td className="py-1 text-green-400 font-bold">BullStrong</td>
                    </tr>
                    <tr className={kalmanSignal === 'Bear' && smaStructure === 'Bear' ? 'bg-red-500/20' : ''}>
                      <td className="py-1">Bear</td>
                      <td className="py-1">Bear</td>
                      <td className="py-1 text-red-400 font-bold">BearStrong</td>
                    </tr>
                    <tr className={!(kalmanSignal === 'Bull' && smaStructure === 'Bull') && !(kalmanSignal === 'Bear' && smaStructure === 'Bear') ? 'bg-yellow-500/20' : ''}>
                      <td className="py-1">Other</td>
                      <td className="py-1">combinations</td>
                      <td className="py-1 text-yellow-400 font-bold">Sideways</td>
                    </tr>
                  </tbody>
                </table>
              )}

              <div className="mt-3 pt-3 border-t border-slate-600 flex items-center gap-2">
                <ArrowRight className="w-4 h-4 text-purple-400" />
                <span className="text-gray-400 text-sm">Current:</span>
                <span className={`font-bold text-base sm:text-lg ${
                  trendState === 'BullStrong' ? 'text-green-400' :
                    trendState === 'BearStrong' ? 'text-red-400' : 'text-yellow-400'
                }`}>
                  {trendState ?? 'N/A'}
                </span>
              </div>
            </div>
          </div>
        </ResponsiveCard>

        {/* Stage 2: Volatility Classification */}
        <ResponsiveCard padding="md">
          <h3 className="text-base sm:text-lg font-semibold mb-3 sm:mb-4 flex items-center gap-2 text-orange-400">
            <span className="bg-orange-500/20 px-2 py-1 rounded text-xs">STAGE 2</span>
            Volatility Classification
          </h3>

          {/* Z-Score Calculation */}
          <div className="mb-4 sm:mb-6">
            <h4 className="text-sm sm:text-md font-medium mb-2 sm:mb-3 text-gray-300">2.1 Volatility Z-Score</h4>
            <div className="bg-slate-700/50 rounded p-3 sm:p-4 space-y-2">
              <div className="flex items-center gap-2 text-sm">
                <span className="text-gray-400">Input:</span>
                <code className="text-cyan-400 text-xs sm:text-sm">Z-Score = {zScore?.toFixed(4) ?? 'N/A'}</code>
              </div>

              <div className="border-t border-slate-600 my-2" />

              <div className="space-y-1 text-xs sm:text-sm">
                <div className={`flex items-center gap-2 ${zScore !== undefined && zScore > upperThreshZ ? 'text-red-400' : 'text-gray-500'}`}>
                  {zScore !== undefined && zScore > upperThreshZ ? <CheckCircle2 className="w-3 h-3 sm:w-4 sm:h-4 flex-shrink-0" /> : <Circle className="w-3 h-3 sm:w-4 sm:h-4 flex-shrink-0" />}
                  <span className="break-words">Z {'>'} <code className="text-yellow-400">{upperThreshZ}</code> → High Volatility</span>
                </div>
                <div className={`flex items-center gap-2 ${zScore !== undefined && zScore < lowerThreshZ ? 'text-green-400' : 'text-gray-500'}`}>
                  {zScore !== undefined && zScore < lowerThreshZ ? <CheckCircle2 className="w-3 h-3 sm:w-4 sm:h-4 flex-shrink-0" /> : <Circle className="w-3 h-3 sm:w-4 sm:h-4 flex-shrink-0" />}
                  <span className="break-words">Z {'<'} <code className="text-yellow-400">{lowerThreshZ}</code> → Low Volatility</span>
                </div>
                <div className={`flex items-center gap-2 ${zScore !== undefined && zScore >= lowerThreshZ && zScore <= upperThreshZ ? 'text-yellow-400' : 'text-gray-500'}`}>
                  {zScore !== undefined && zScore >= lowerThreshZ && zScore <= upperThreshZ ? <CheckCircle2 className="w-3 h-3 sm:w-4 sm:h-4 flex-shrink-0" /> : <Circle className="w-3 h-3 sm:w-4 sm:h-4 flex-shrink-0" />}
                  <span>Otherwise → Transition (use previous)</span>
                </div>
              </div>

              <div className="border-t border-slate-600 my-2" />

              <div className="flex items-center gap-2">
                <span className="text-gray-400 text-sm">Result:</span>
                <span className={`font-bold text-sm sm:text-base ${volState === 'Low' ? 'text-green-400' : 'text-red-400'}`}>
                  {volState ?? 'N/A'}
                </span>
              </div>
            </div>
          </div>

          {/* Vol-Crush Override */}
          <div className="mb-4 sm:mb-6">
            <h4 className="text-sm sm:text-md font-medium mb-2 sm:mb-3 text-gray-300">2.2 Vol-Crush Override</h4>
            <div className="bg-slate-700/50 rounded p-3 sm:p-4 space-y-2">
              <div className="text-xs sm:text-sm text-gray-400 mb-2">
                Emergency override when volatility collapses rapidly
              </div>

              <div className="space-y-1 text-xs sm:text-sm">
                <div className="flex items-center gap-2">
                  <span className="text-gray-400">Lookback:</span>
                  <code className="text-yellow-400">{volCrushLookback} days</code>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-gray-400">Threshold:</span>
                  <code className="text-yellow-400">{(volCrushThreshold * 100).toFixed(0)}% drop</code>
                </div>
              </div>

              <div className="border-t border-slate-600 my-2" />

              <div className="flex items-center gap-2">
                <span className="text-gray-400 text-sm">Status:</span>
                {volCrushTriggered ? (
                  <span className="flex items-center gap-1 text-red-400 font-bold text-sm">
                    <Zap className="w-3 h-3 sm:w-4 sm:h-4" />
                    TRIGGERED → Force Low Vol
                  </span>
                ) : (
                  <span className="text-gray-500 text-sm">Inactive</span>
                )}
              </div>
            </div>
          </div>

          {/* Hysteresis Note */}
          <div className="bg-slate-700/30 rounded p-3 sm:p-4 text-xs sm:text-sm text-gray-400">
            <div className="font-medium text-gray-300 mb-2">Note: Hysteresis State Machine</div>
            <p>
              Volatility state uses hysteresis - once in High/Low, it stays until
              the opposite threshold is crossed. The "transition zone" between
              {' '}{lowerThreshZ} and {upperThreshZ} maintains the previous state.
            </p>
          </div>
        </ResponsiveCard>

        {/* Stage 3: Cell Assignment */}
        <ResponsiveCard padding="md">
          <h3 className="text-base sm:text-lg font-semibold mb-3 sm:mb-4 flex items-center gap-2 text-purple-400">
            <span className="bg-purple-500/20 px-2 py-1 rounded text-xs">STAGE 3</span>
            Cell Assignment (6-Cell Matrix)
          </h3>

          {isMobile ? (
            // Mobile: Card view for cell matrix
            <div className="space-y-3">
              {/* BullStrong Row */}
              <div>
                <div className="text-green-400 font-medium text-sm mb-2">BullStrong</div>
                <div className="grid grid-cols-2 gap-2">
                  <div className={`p-3 rounded text-center ${currentCell === 1 ? 'bg-green-500/30 border border-green-500/50' : 'bg-slate-700/50'}`}>
                    <div className="font-bold">Cell 1</div>
                    <div className="text-xs text-gray-400">Aggressive</div>
                    <div className="text-xs text-green-400 mt-1">Low Vol</div>
                  </div>
                  <div className={`p-3 rounded text-center ${currentCell === 2 ? 'bg-green-500/30 border border-green-500/50' : 'bg-slate-700/50'}`}>
                    <div className="font-bold">Cell 2</div>
                    <div className="text-xs text-gray-400">Cautious Bull</div>
                    <div className="text-xs text-red-400 mt-1">High Vol</div>
                  </div>
                </div>
              </div>

              {/* Sideways Row */}
              <div>
                <div className="text-yellow-400 font-medium text-sm mb-2">Sideways</div>
                <div className="grid grid-cols-2 gap-2">
                  <div className={`p-3 rounded text-center ${currentCell === 3 ? 'bg-yellow-500/30 border border-yellow-500/50' : 'bg-slate-700/50'}`}>
                    <div className="font-bold">Cell 3</div>
                    <div className="text-xs text-gray-400">Neutral</div>
                    <div className="text-xs text-green-400 mt-1">Low Vol</div>
                  </div>
                  <div className={`p-3 rounded text-center ${currentCell === 4 ? 'bg-yellow-500/30 border border-yellow-500/50' : 'bg-slate-700/50'}`}>
                    <div className="font-bold">Cell 4</div>
                    <div className="text-xs text-gray-400">Defensive</div>
                    <div className="text-xs text-red-400 mt-1">High Vol</div>
                  </div>
                </div>
              </div>

              {/* BearStrong Row */}
              <div>
                <div className="text-red-400 font-medium text-sm mb-2">BearStrong</div>
                <div className="grid grid-cols-2 gap-2">
                  <div className={`p-3 rounded text-center ${currentCell === 5 ? 'bg-red-500/30 border border-red-500/50' : 'bg-slate-700/50'}`}>
                    <div className="font-bold">Cell 5</div>
                    <div className="text-xs text-gray-400">Caution Bear</div>
                    <div className="text-xs text-green-400 mt-1">Low Vol</div>
                  </div>
                  <div className={`p-3 rounded text-center ${currentCell === 6 ? 'bg-red-500/30 border border-red-500/50' : 'bg-slate-700/50'}`}>
                    <div className="font-bold">Cell 6</div>
                    <div className="text-xs text-gray-400">Max Defense</div>
                    <div className="text-xs text-red-400 mt-1">High Vol</div>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            // Desktop: Table view
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-600">
                    <th className="py-2 px-3 text-left text-gray-400">Trend</th>
                    <th className="py-2 px-3 text-center text-green-400">Low Vol</th>
                    <th className="py-2 px-3 text-center text-red-400">High Vol</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td className="py-2 px-3 text-green-400 font-medium">BullStrong</td>
                    <td className={`py-2 px-3 text-center ${currentCell === 1 ? 'bg-green-500/30 rounded' : ''}`}>
                      <div className="font-bold">Cell 1</div>
                      <div className="text-xs text-gray-400">Aggressive</div>
                    </td>
                    <td className={`py-2 px-3 text-center ${currentCell === 2 ? 'bg-green-500/30 rounded' : ''}`}>
                      <div className="font-bold">Cell 2</div>
                      <div className="text-xs text-gray-400">Cautious Bull</div>
                    </td>
                  </tr>
                  <tr>
                    <td className="py-2 px-3 text-yellow-400 font-medium">Sideways</td>
                    <td className={`py-2 px-3 text-center ${currentCell === 3 ? 'bg-yellow-500/30 rounded' : ''}`}>
                      <div className="font-bold">Cell 3</div>
                      <div className="text-xs text-gray-400">Neutral</div>
                    </td>
                    <td className={`py-2 px-3 text-center ${currentCell === 4 ? 'bg-yellow-500/30 rounded' : ''}`}>
                      <div className="font-bold">Cell 4</div>
                      <div className="text-xs text-gray-400">Defensive</div>
                    </td>
                  </tr>
                  <tr>
                    <td className="py-2 px-3 text-red-400 font-medium">BearStrong</td>
                    <td className={`py-2 px-3 text-center ${currentCell === 5 ? 'bg-red-500/30 rounded' : ''}`}>
                      <div className="font-bold">Cell 5</div>
                      <div className="text-xs text-gray-400">Caution Bear</div>
                    </td>
                    <td className={`py-2 px-3 text-center ${currentCell === 6 ? 'bg-red-500/30 rounded' : ''}`}>
                      <div className="font-bold">Cell 6</div>
                      <div className="text-xs text-gray-400">Maximum Defense</div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          )}

          <div className="mt-4 pt-4 border-t border-slate-600 flex items-center justify-center gap-3">
            <ArrowRight className="w-4 h-4 sm:w-5 sm:h-5 text-purple-400" />
            <span className="text-gray-400 text-sm">Current Cell:</span>
            <span className={`text-xl sm:text-2xl font-bold ${
              currentCell && currentCell <= 2 ? 'text-green-400' :
                currentCell && currentCell <= 4 ? 'text-yellow-400' : 'text-red-400'
            }`}>
              {currentCell ?? 'N/A'}
            </span>
          </div>
        </ResponsiveCard>

        {/* Cell 1 Exit Confirmation (v3.5d feature) */}
        {cell1ExitConfirmationEnabled && (
          <ResponsiveCard padding="md">
            <h3 className="text-base sm:text-lg font-semibold mb-3 sm:mb-4 flex items-center gap-2 text-amber-400">
              <span className="bg-amber-500/20 px-2 py-1 rounded text-xs">v3.5d</span>
              Cell 1 Exit Confirmation
            </h3>

            <div className="bg-slate-700/50 rounded p-3 sm:p-4 space-y-2">
              <div className="text-xs sm:text-sm text-gray-400 mb-3">
                Requires {cell1ExitConfirmationDays} consecutive days below T_norm bull threshold before exiting Cell 1 to Sideways.
                Prevents whipsaw during brief pullbacks.
              </div>

              <div className="space-y-2 text-xs sm:text-sm">
                <div className="flex items-center justify-between">
                  <span className="text-gray-400">Confirmation Days Required:</span>
                  <code className="text-yellow-400 font-bold">{cell1ExitConfirmationDays}</code>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-gray-400">Current Pending Days:</span>
                  <code className={`font-bold ${
                    cell1ExitPendingDays !== undefined && cell1ExitPendingDays > 0
                      ? 'text-amber-400'
                      : 'text-gray-500'
                  }`}>
                    {cell1ExitPendingDays ?? 0}
                  </code>
                </div>
              </div>

              <div className="border-t border-slate-600 my-2" />

              {/* Progress bar for exit confirmation */}
              <div className="space-y-1">
                <div className="flex items-center justify-between text-xs text-gray-400">
                  <span>Exit Confirmation Progress</span>
                  <span>
                    {cell1ExitPendingDays ?? 0} / {cell1ExitConfirmationDays}
                  </span>
                </div>
                <div className="w-full bg-slate-600 rounded-full h-2">
                  <div
                    className={`h-2 rounded-full transition-all duration-300 ${
                      cell1ExitPendingDays !== undefined && cell1ExitPendingDays >= cell1ExitConfirmationDays
                        ? 'bg-red-500'
                        : cell1ExitPendingDays !== undefined && cell1ExitPendingDays > 0
                          ? 'bg-amber-500'
                          : 'bg-gray-500'
                    }`}
                    style={{
                      width: `${Math.min(100, ((cell1ExitPendingDays ?? 0) / cell1ExitConfirmationDays) * 100)}%`
                    }}
                  />
                </div>
              </div>

              <div className="border-t border-slate-600 my-2" />

              <div className="flex items-center gap-2">
                <span className="text-gray-400 text-sm">Status:</span>
                {currentCell === 1 ? (
                  cell1ExitPendingDays !== undefined && cell1ExitPendingDays >= cell1ExitConfirmationDays ? (
                    <span className="text-red-400 font-bold text-sm">EXIT CONFIRMED → Transitioning to Sideways</span>
                  ) : cell1ExitPendingDays !== undefined && cell1ExitPendingDays > 0 ? (
                    <span className="text-amber-400 font-bold text-sm">PENDING ({cell1ExitPendingDays}/{cell1ExitConfirmationDays}) → Staying in Cell 1</span>
                  ) : (
                    <span className="text-green-400 font-bold text-sm">STABLE → In Cell 1, no exit signals</span>
                  )
                ) : (
                  <span className="text-gray-500 text-sm">N/A (Not in Cell 1)</span>
                )}
              </div>
            </div>
          </ResponsiveCard>
        )}

        {/* Stage 4: Treasury Overlay */}
        <ResponsiveCard padding="md">
          <h3 className="text-base sm:text-lg font-semibold mb-3 sm:mb-4 flex items-center gap-2 text-cyan-400">
            <span className="bg-cyan-500/20 px-2 py-1 rounded text-xs">STAGE 4</span>
            Treasury Overlay
          </h3>

          <div className="mb-3 sm:mb-4 text-xs sm:text-sm text-gray-400">
            Applies to defensive cells (4, 5, 6) to determine bond allocation
          </div>

          <div className="bg-slate-700/50 rounded p-3 sm:p-4 space-y-2">
            <div className="flex items-center gap-2 text-xs sm:text-sm">
              <span className="text-gray-400">Bond SMA Fast ({bondSmaFast}d):</span>
              <code className="text-cyan-400">{getIndicator('bond_sma_fast')?.value ?? 'N/A'}</code>
            </div>
            <div className="flex items-center gap-2 text-xs sm:text-sm">
              <span className="text-gray-400">Bond SMA Slow ({bondSmaSlow}d):</span>
              <code className="text-cyan-400">{getIndicator('bond_sma_slow')?.value ?? 'N/A'}</code>
            </div>

            <div className="border-t border-slate-600 my-2" />

            <div className="space-y-1 text-xs sm:text-sm">
              <div className="flex items-center gap-2">
                <TrendingUp className="w-3 h-3 sm:w-4 sm:h-4 text-green-400" />
                <span>Fast {'>'} Slow → <span className="text-green-400 font-bold">TMF</span> (Bull Bonds)</span>
              </div>
              <div className="flex items-center gap-2">
                <TrendingDown className="w-3 h-3 sm:w-4 sm:h-4 text-red-400" />
                <span>Fast {'<'} Slow → <span className="text-red-400 font-bold">TMV</span> (Bear Bonds)</span>
              </div>
            </div>

            <div className="border-t border-slate-600 my-2" />

            <div className="flex items-center gap-2">
              <span className="text-gray-400 text-sm">Bond Trend:</span>
              <span className="font-bold text-sm sm:text-base">
                {getIndicator('bond_trend')?.signal ?? 'N/A'}
              </span>
            </div>
          </div>

          {currentCell && currentCell >= 4 ? (
            <div className="mt-3 sm:mt-4 p-2 sm:p-3 bg-cyan-500/20 rounded text-cyan-400 text-xs sm:text-sm flex items-center gap-2">
              <Shield className="w-3 h-3 sm:w-4 sm:h-4 flex-shrink-0" />
              <span>Treasury Overlay ACTIVE - Bonds in allocation</span>
            </div>
          ) : (
            <div className="mt-3 sm:mt-4 p-2 sm:p-3 bg-slate-700/50 rounded text-gray-500 text-xs sm:text-sm">
              Treasury Overlay not active (Cell {currentCell} is not defensive)
            </div>
          )}
        </ResponsiveCard>
      </div>

      {/* Final Allocation Table */}
      <ResponsiveCard padding="md">
        <h3 className="text-base sm:text-lg font-semibold mb-3 sm:mb-4 flex items-center gap-2 text-green-400">
          <Activity className="w-4 h-4 sm:w-5 sm:h-5" />
          Target Allocation by Cell
        </h3>

        {isMobile ? (
          // Mobile: Card view for allocations
          <div className="space-y-3">
            {[
              { cell: 1, regime: 'BullStrong + Low Vol', tqqq: 60, qqq: 40, psq: 0, bonds: 0, cash: 0 },
              { cell: 2, regime: 'BullStrong + High Vol', tqqq: 0, qqq: 100, psq: 0, bonds: 0, cash: 0 },
              { cell: 3, regime: 'Sideways + Low Vol', tqqq: 20, qqq: 80, psq: 0, bonds: 0, cash: 0 },
              { cell: 4, regime: 'Sideways + High Vol', tqqq: 0, qqq: 0, psq: 0, bonds: 100, cash: 0 },
              { cell: 5, regime: 'BearStrong + Low Vol', tqqq: 0, qqq: 50, psq: 0, bonds: 50, cash: 0 },
              { cell: 6, regime: 'BearStrong + High Vol', tqqq: 0, qqq: 0, psq: 50, bonds: 0, cash: 50 },
            ].map(row => (
              <div
                key={row.cell}
                className={`p-3 rounded ${currentCell === row.cell ? 'bg-purple-500/20 border border-purple-500/50' : 'bg-slate-700/50'}`}
              >
                <div className="flex justify-between items-center mb-2">
                  <span className={`font-bold text-lg ${
                    row.cell <= 2 ? 'text-green-400' :
                      row.cell <= 4 ? 'text-yellow-400' : 'text-red-400'
                  }`}>
                    Cell {row.cell}
                  </span>
                  {currentCell === row.cell && (
                    <span className="text-xs bg-purple-500 px-2 py-0.5 rounded text-white">ACTIVE</span>
                  )}
                </div>
                <div className="text-xs text-gray-400 mb-2">{row.regime}</div>
                <div className="grid grid-cols-5 gap-1 text-xs text-center">
                  <div>
                    <div className="text-blue-400 font-medium">TQQQ</div>
                    <div>{row.tqqq}%</div>
                  </div>
                  <div>
                    <div className="text-green-400 font-medium">QQQ</div>
                    <div>{row.qqq}%</div>
                  </div>
                  <div>
                    <div className="text-orange-400 font-medium">PSQ</div>
                    <div>{row.psq}%</div>
                  </div>
                  <div>
                    <div className="text-cyan-400 font-medium">Bonds</div>
                    <div>{row.bonds}%</div>
                  </div>
                  <div>
                    <div className="text-gray-400 font-medium">Cash</div>
                    <div>{row.cash}%</div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          // Desktop: Table view
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-600">
                  <th className="py-2 px-3 text-left text-gray-400">Cell</th>
                  <th className="py-2 px-3 text-left text-gray-400">Regime</th>
                  <th className="py-2 px-3 text-center text-blue-400">TQQQ</th>
                  <th className="py-2 px-3 text-center text-green-400">QQQ</th>
                  <th className="py-2 px-3 text-center text-orange-400">PSQ</th>
                  <th className="py-2 px-3 text-center text-cyan-400">TMF/TMV</th>
                  <th className="py-2 px-3 text-center text-gray-400">CASH</th>
                </tr>
              </thead>
              <tbody>
                {[
                  { cell: 1, regime: 'BullStrong + Low Vol', tqqq: 60, qqq: 40, psq: 0, bonds: 0, cash: 0 },
                  { cell: 2, regime: 'BullStrong + High Vol', tqqq: 0, qqq: 100, psq: 0, bonds: 0, cash: 0 },
                  { cell: 3, regime: 'Sideways + Low Vol', tqqq: 20, qqq: 80, psq: 0, bonds: 0, cash: 0 },
                  { cell: 4, regime: 'Sideways + High Vol', tqqq: 0, qqq: 0, psq: 0, bonds: 100, cash: 0 },
                  { cell: 5, regime: 'BearStrong + Low Vol', tqqq: 0, qqq: 50, psq: 0, bonds: 50, cash: 0 },
                  { cell: 6, regime: 'BearStrong + High Vol', tqqq: 0, qqq: 0, psq: 50, bonds: 0, cash: 50 },
                ].map(row => (
                  <tr
                    key={row.cell}
                    className={currentCell === row.cell ? 'bg-purple-500/20' : ''}
                  >
                    <td className="py-2 px-3 font-bold">{row.cell}</td>
                    <td className="py-2 px-3 text-gray-300">{row.regime}</td>
                    <td className="py-2 px-3 text-center text-blue-400">{row.tqqq}%</td>
                    <td className="py-2 px-3 text-center text-green-400">{row.qqq}%</td>
                    <td className="py-2 px-3 text-center text-orange-400">{row.psq}%</td>
                    <td className="py-2 px-3 text-center text-cyan-400">{row.bonds}%</td>
                    <td className="py-2 px-3 text-center text-gray-400">{row.cash}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {currentCell && (
          <div className="mt-3 sm:mt-4 pt-3 sm:pt-4 border-t border-slate-600 text-center text-sm">
            <span className="text-gray-400">Currently in </span>
            <span className="text-purple-400 font-bold">Cell {currentCell}</span>
            <span className="text-gray-400"> - see highlighted {isMobile ? 'card' : 'row'} above</span>
          </div>
        )}
      </ResponsiveCard>
    </div>
  )
}

export default DecisionTreeV2
