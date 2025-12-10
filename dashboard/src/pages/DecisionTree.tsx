import { useQuery } from '@tanstack/react-query'
import { indicatorsApi, configApi, IndicatorsResponse, ConfigResponse } from '../api/client'
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
} from 'lucide-react'

function DecisionTree() {
  // Fetch config for thresholds using the shared API client
  // This uses relative paths that work through nginx in Docker
  const { data: config, isLoading: configLoading } = useQuery<ConfigResponse>({
    queryKey: ['config'],
    queryFn: async () => {
      const response = await configApi.getConfig()
      return response.data
    },
    refetchInterval: 30000,
  })

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
  const getParam = (name: string): number | string | boolean | undefined => {
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
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold flex items-center gap-2">
          <GitBranch className="w-6 h-6 text-purple-400" />
          Cell Decision Tree
        </h2>
        <div className="text-sm text-gray-400">
          Strategy: {config?.strategy_name ?? 'Unknown'}
        </div>
      </div>

      {/* Decision Flow Visualization */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

        {/* Stage 1: Trend Classification */}
        <div className="bg-slate-800 rounded-lg p-6 border border-slate-700">
          <h3 className="text-lg font-semibold mb-4 flex items-center gap-2 text-blue-400">
            <span className="bg-blue-500/20 px-2 py-1 rounded text-xs">STAGE 1</span>
            Trend Classification
          </h3>

          {/* Kalman Trend Detector */}
          <div className="mb-6">
            <h4 className="text-md font-medium mb-3 text-gray-300">1.1 Kalman Trend Detector</h4>
            <div className="bg-slate-700/50 rounded p-4 space-y-2">
              <div className="flex items-center gap-2">
                <span className="text-gray-400">Input:</span>
                <code className="text-cyan-400">T_norm = {tNorm?.toFixed(4) ?? 'N/A'}</code>
              </div>

              <div className="border-t border-slate-600 my-2" />

              <div className="space-y-1 text-sm">
                <div className={`flex items-center gap-2 ${kalmanSignal === 'Bull' ? 'text-green-400' : 'text-gray-500'}`}>
                  {kalmanSignal === 'Bull' ? <CheckCircle2 className="w-4 h-4" /> : <Circle className="w-4 h-4" />}
                  <span>T_norm {'>'} <code className="text-yellow-400">{tNormBullThresh}</code> → Bull</span>
                </div>
                <div className={`flex items-center gap-2 ${kalmanSignal === 'Bear' ? 'text-red-400' : 'text-gray-500'}`}>
                  {kalmanSignal === 'Bear' ? <CheckCircle2 className="w-4 h-4" /> : <Circle className="w-4 h-4" />}
                  <span>T_norm {'<'} <code className="text-yellow-400">{tNormBearThresh}</code> → Bear</span>
                </div>
                <div className={`flex items-center gap-2 ${kalmanSignal === 'Neutral' ? 'text-yellow-400' : 'text-gray-500'}`}>
                  {kalmanSignal === 'Neutral' ? <CheckCircle2 className="w-4 h-4" /> : <Circle className="w-4 h-4" />}
                  <span>Otherwise → Neutral</span>
                </div>
              </div>

              <div className="border-t border-slate-600 my-2" />

              <div className="flex items-center gap-2">
                <span className="text-gray-400">Result:</span>
                <span className={`font-bold ${
                  kalmanSignal === 'Bull' ? 'text-green-400' :
                    kalmanSignal === 'Bear' ? 'text-red-400' : 'text-yellow-400'
                }`}>
                  {kalmanSignal}
                </span>
              </div>
            </div>
          </div>

          {/* SMA Structure */}
          <div className="mb-6">
            <h4 className="text-md font-medium mb-3 text-gray-300">1.2 SMA Structure</h4>
            <div className="bg-slate-700/50 rounded p-4 space-y-2">
              <div className="flex items-center gap-2 text-sm">
                <span className="text-gray-400">SMA Fast ({smaFastPeriod}d):</span>
                <code className="text-cyan-400">{smaFast?.toFixed(2) ?? 'N/A'}</code>
              </div>
              <div className="flex items-center gap-2 text-sm">
                <span className="text-gray-400">SMA Slow ({smaSlowPeriod}d):</span>
                <code className="text-cyan-400">{smaSlow?.toFixed(2) ?? 'N/A'}</code>
              </div>

              <div className="border-t border-slate-600 my-2" />

              <div className="space-y-1 text-sm">
                <div className={`flex items-center gap-2 ${smaStructure === 'Bull' ? 'text-green-400' : 'text-gray-500'}`}>
                  {smaStructure === 'Bull' ? <CheckCircle2 className="w-4 h-4" /> : <Circle className="w-4 h-4" />}
                  <span>Fast {'>'} Slow → Bull Structure</span>
                </div>
                <div className={`flex items-center gap-2 ${smaStructure === 'Bear' ? 'text-red-400' : 'text-gray-500'}`}>
                  {smaStructure === 'Bear' ? <CheckCircle2 className="w-4 h-4" /> : <Circle className="w-4 h-4" />}
                  <span>Fast {'<'} Slow → Bear Structure</span>
                </div>
              </div>

              <div className="border-t border-slate-600 my-2" />

              <div className="flex items-center gap-2">
                <span className="text-gray-400">Result:</span>
                <span className={`font-bold ${smaStructure === 'Bull' ? 'text-green-400' : 'text-red-400'}`}>
                  {smaStructure}
                </span>
              </div>
            </div>
          </div>

          {/* Combined Trend */}
          <div>
            <h4 className="text-md font-medium mb-3 text-gray-300">1.3 Combined Trend State</h4>
            <div className="bg-slate-700/50 rounded p-4">
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

              <div className="mt-3 pt-3 border-t border-slate-600 flex items-center gap-2">
                <ArrowRight className="w-4 h-4 text-purple-400" />
                <span className="text-gray-400">Current:</span>
                <span className={`font-bold text-lg ${
                  trendState === 'BullStrong' ? 'text-green-400' :
                    trendState === 'BearStrong' ? 'text-red-400' : 'text-yellow-400'
                }`}>
                  {trendState ?? 'N/A'}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Stage 2: Volatility Classification */}
        <div className="bg-slate-800 rounded-lg p-6 border border-slate-700">
          <h3 className="text-lg font-semibold mb-4 flex items-center gap-2 text-orange-400">
            <span className="bg-orange-500/20 px-2 py-1 rounded text-xs">STAGE 2</span>
            Volatility Classification
          </h3>

          {/* Z-Score Calculation */}
          <div className="mb-6">
            <h4 className="text-md font-medium mb-3 text-gray-300">2.1 Volatility Z-Score</h4>
            <div className="bg-slate-700/50 rounded p-4 space-y-2">
              <div className="flex items-center gap-2">
                <span className="text-gray-400">Input:</span>
                <code className="text-cyan-400">Z-Score = {zScore?.toFixed(4) ?? 'N/A'}</code>
              </div>

              <div className="border-t border-slate-600 my-2" />

              <div className="space-y-1 text-sm">
                <div className={`flex items-center gap-2 ${zScore !== undefined && zScore > upperThreshZ ? 'text-red-400' : 'text-gray-500'}`}>
                  {zScore !== undefined && zScore > upperThreshZ ? <CheckCircle2 className="w-4 h-4" /> : <Circle className="w-4 h-4" />}
                  <span>Z {'>'} <code className="text-yellow-400">{upperThreshZ}</code> → High Volatility</span>
                </div>
                <div className={`flex items-center gap-2 ${zScore !== undefined && zScore < lowerThreshZ ? 'text-green-400' : 'text-gray-500'}`}>
                  {zScore !== undefined && zScore < lowerThreshZ ? <CheckCircle2 className="w-4 h-4" /> : <Circle className="w-4 h-4" />}
                  <span>Z {'<'} <code className="text-yellow-400">{lowerThreshZ}</code> → Low Volatility</span>
                </div>
                <div className={`flex items-center gap-2 ${zScore !== undefined && zScore >= lowerThreshZ && zScore <= upperThreshZ ? 'text-yellow-400' : 'text-gray-500'}`}>
                  {zScore !== undefined && zScore >= lowerThreshZ && zScore <= upperThreshZ ? <CheckCircle2 className="w-4 h-4" /> : <Circle className="w-4 h-4" />}
                  <span>Otherwise → Transition (use previous)</span>
                </div>
              </div>

              <div className="border-t border-slate-600 my-2" />

              <div className="flex items-center gap-2">
                <span className="text-gray-400">Result:</span>
                <span className={`font-bold ${volState === 'Low' ? 'text-green-400' : 'text-red-400'}`}>
                  {volState ?? 'N/A'}
                </span>
              </div>
            </div>
          </div>

          {/* Vol-Crush Override */}
          <div className="mb-6">
            <h4 className="text-md font-medium mb-3 text-gray-300">2.2 Vol-Crush Override</h4>
            <div className="bg-slate-700/50 rounded p-4 space-y-2">
              <div className="text-sm text-gray-400 mb-2">
                Emergency override when volatility collapses rapidly
              </div>

              <div className="space-y-1 text-sm">
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
                <span className="text-gray-400">Status:</span>
                {volCrushTriggered ? (
                  <span className="flex items-center gap-1 text-red-400 font-bold">
                    <Zap className="w-4 h-4" />
                    TRIGGERED → Force Low Vol
                  </span>
                ) : (
                  <span className="text-gray-500">Inactive</span>
                )}
              </div>
            </div>
          </div>

          {/* Hysteresis Note */}
          <div className="bg-slate-700/30 rounded p-4 text-sm text-gray-400">
            <div className="font-medium text-gray-300 mb-2">Note: Hysteresis State Machine</div>
            <p>
              Volatility state uses hysteresis - once in High/Low, it stays until
              the opposite threshold is crossed. The "transition zone" between
              {lowerThreshZ} and {upperThreshZ} maintains the previous state.
            </p>
          </div>
        </div>

        {/* Stage 3: Cell Assignment */}
        <div className="bg-slate-800 rounded-lg p-6 border border-slate-700">
          <h3 className="text-lg font-semibold mb-4 flex items-center gap-2 text-purple-400">
            <span className="bg-purple-500/20 px-2 py-1 rounded text-xs">STAGE 3</span>
            Cell Assignment (6-Cell Matrix)
          </h3>

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

          <div className="mt-4 pt-4 border-t border-slate-600 flex items-center justify-center gap-3">
            <ArrowRight className="w-5 h-5 text-purple-400" />
            <span className="text-gray-400">Current Cell:</span>
            <span className={`text-2xl font-bold ${
              currentCell && currentCell <= 2 ? 'text-green-400' :
                currentCell && currentCell <= 4 ? 'text-yellow-400' : 'text-red-400'
            }`}>
              {currentCell ?? 'N/A'}
            </span>
          </div>
        </div>

        {/* Stage 4: Treasury Overlay */}
        <div className="bg-slate-800 rounded-lg p-6 border border-slate-700">
          <h3 className="text-lg font-semibold mb-4 flex items-center gap-2 text-cyan-400">
            <span className="bg-cyan-500/20 px-2 py-1 rounded text-xs">STAGE 4</span>
            Treasury Overlay
          </h3>

          <div className="mb-4 text-sm text-gray-400">
            Applies to defensive cells (4, 5, 6) to determine bond allocation
          </div>

          <div className="bg-slate-700/50 rounded p-4 space-y-2">
            <div className="flex items-center gap-2 text-sm">
              <span className="text-gray-400">Bond SMA Fast ({bondSmaFast}d):</span>
              <code className="text-cyan-400">{getIndicator('bond_sma_fast')?.value ?? 'N/A'}</code>
            </div>
            <div className="flex items-center gap-2 text-sm">
              <span className="text-gray-400">Bond SMA Slow ({bondSmaSlow}d):</span>
              <code className="text-cyan-400">{getIndicator('bond_sma_slow')?.value ?? 'N/A'}</code>
            </div>

            <div className="border-t border-slate-600 my-2" />

            <div className="space-y-1 text-sm">
              <div className="flex items-center gap-2">
                <TrendingUp className="w-4 h-4 text-green-400" />
                <span>Fast {'>'} Slow → <span className="text-green-400 font-bold">TMF</span> (Bull Bonds)</span>
              </div>
              <div className="flex items-center gap-2">
                <TrendingDown className="w-4 h-4 text-red-400" />
                <span>Fast {'<'} Slow → <span className="text-red-400 font-bold">TMV</span> (Bear Bonds)</span>
              </div>
            </div>

            <div className="border-t border-slate-600 my-2" />

            <div className="flex items-center gap-2">
              <span className="text-gray-400">Bond Trend:</span>
              <span className="font-bold">
                {getIndicator('bond_trend')?.signal ?? 'N/A'}
              </span>
            </div>
          </div>

          {currentCell && currentCell >= 4 ? (
            <div className="mt-4 p-3 bg-cyan-500/20 rounded text-cyan-400 text-sm flex items-center gap-2">
              <Shield className="w-4 h-4" />
              Treasury Overlay ACTIVE - Bonds in allocation
            </div>
          ) : (
            <div className="mt-4 p-3 bg-slate-700/50 rounded text-gray-500 text-sm">
              Treasury Overlay not active (Cell {currentCell} is not defensive)
            </div>
          )}
        </div>
      </div>

      {/* Final Allocation Table */}
      <div className="bg-slate-800 rounded-lg p-6 border border-slate-700">
        <h3 className="text-lg font-semibold mb-4 flex items-center gap-2 text-green-400">
          <Activity className="w-5 h-5" />
          Target Allocation by Cell
        </h3>

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
                { cell: 1, regime: 'BullStrong + Low Vol', tqqq: 100, qqq: 0, psq: 0, bonds: 0, cash: 0 },
                { cell: 2, regime: 'BullStrong + High Vol', tqqq: 40, qqq: 60, psq: 0, bonds: 0, cash: 0 },
                { cell: 3, regime: 'Sideways + Low Vol', tqqq: 20, qqq: 80, psq: 0, bonds: 0, cash: 0 },
                { cell: 4, regime: 'Sideways + High Vol', tqqq: 0, qqq: 40, psq: 0, bonds: 40, cash: 20 },
                { cell: 5, regime: 'BearStrong + Low Vol', tqqq: 0, qqq: 40, psq: 20, bonds: 40, cash: 0 },
                { cell: 6, regime: 'BearStrong + High Vol', tqqq: 0, qqq: 0, psq: 40, bonds: 40, cash: 20 },
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

        {currentCell && (
          <div className="mt-4 pt-4 border-t border-slate-600 text-center">
            <span className="text-gray-400">Currently in </span>
            <span className="text-purple-400 font-bold">Cell {currentCell}</span>
            <span className="text-gray-400"> - see highlighted row above</span>
          </div>
        )}
      </div>
    </div>
  )
}

export default DecisionTree
