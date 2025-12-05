import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { configApi, ConfigParameter } from '../api/client'

function Config() {
  const queryClient = useQueryClient()
  const [editingParam, setEditingParam] = useState<string | null>(null)
  const [editValue, setEditValue] = useState<string>('')
  const [editReason, setEditReason] = useState<string>('')

  const { data: config, isLoading, error } = useQuery({
    queryKey: ['config'],
    queryFn: () => configApi.getConfig().then(res => res.data),
  })

  const updateConfig = useMutation({
    mutationFn: (data: { parameter_name: string; new_value: unknown; reason?: string }) =>
      configApi.updateConfig(data).then(res => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['config'] })
      setEditingParam(null)
      setEditValue('')
      setEditReason('')
    },
  })

  const resetParameter = useMutation({
    mutationFn: (name: string) => configApi.resetParameter(name).then(res => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['config'] })
    },
  })

  const handleStartEdit = (param: ConfigParameter) => {
    setEditingParam(param.name)
    setEditValue(String(param.value))
    setEditReason('')
  }

  const handleSaveEdit = (param: ConfigParameter) => {
    let parsedValue: unknown = editValue

    // Parse value based on type
    if (param.constraints?.value_type === 'int') {
      parsedValue = parseInt(editValue, 10)
    } else if (param.constraints?.value_type === 'float') {
      parsedValue = parseFloat(editValue)
    } else if (param.constraints?.value_type === 'bool') {
      parsedValue = editValue.toLowerCase() === 'true'
    }

    updateConfig.mutate({
      parameter_name: param.name,
      new_value: parsedValue,
      reason: editReason || undefined,
    })
  }

  const handleReset = (name: string) => {
    if (window.confirm(`Reset ${name} to its default value?`)) {
      resetParameter.mutate(name)
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-400"></div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-6 text-center text-red-400">
        Failed to load configuration
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">Configuration</h2>
        {config && (config.active_overrides ?? 0) > 0 && (
          <span className="px-3 py-1 bg-yellow-600/30 text-yellow-400 rounded-full text-sm">
            {config.active_overrides} override(s) active
          </span>
        )}
      </div>

      {/* Strategy Info */}
      {config && (
        <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-sm text-gray-400">Strategy</div>
              <div className="text-lg font-medium">{config.strategy_name}</div>
            </div>
            {config.last_modified && (
              <div className="text-sm text-gray-400">
                Last modified: {new Date(config.last_modified).toLocaleString()}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Parameters Table */}
      <div className="bg-slate-800 rounded-lg border border-slate-700 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead className="text-sm text-gray-400 bg-slate-700/50">
              <tr>
                <th className="px-4 py-3">Parameter</th>
                <th className="px-4 py-3">Current Value</th>
                <th className="px-4 py-3">Default</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Constraints</th>
                <th className="px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {config?.parameters.map((param: ConfigParameter) => (
                <tr key={param.name} className={`border-t border-slate-700/50 ${
                  param.is_overridden ? 'bg-yellow-900/10' : ''
                }`}>
                  <td className="px-4 py-3">
                    <div className="font-medium">{param.name}</div>
                    {param.description && (
                      <div className="text-sm text-gray-400">{param.description}</div>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {editingParam === param.name ? (
                      <div className="space-y-2">
                        {param.constraints?.allowed_values ? (
                          <select
                            value={editValue}
                            onChange={(e) => setEditValue(e.target.value)}
                            className="px-2 py-1 bg-slate-700 rounded border border-slate-600 w-full"
                          >
                            {param.constraints.allowed_values.map((v) => (
                              <option key={String(v)} value={String(v)}>{String(v)}</option>
                            ))}
                          </select>
                        ) : param.constraints?.value_type === 'bool' ? (
                          <select
                            value={editValue}
                            onChange={(e) => setEditValue(e.target.value)}
                            className="px-2 py-1 bg-slate-700 rounded border border-slate-600 w-full"
                          >
                            <option value="true">true</option>
                            <option value="false">false</option>
                          </select>
                        ) : (
                          <input
                            type={param.constraints?.value_type === 'int' || param.constraints?.value_type === 'float' ? 'number' : 'text'}
                            value={editValue}
                            onChange={(e) => setEditValue(e.target.value)}
                            min={param.constraints?.min_value}
                            max={param.constraints?.max_value}
                            step={param.constraints?.value_type === 'float' ? '0.01' : '1'}
                            className="px-2 py-1 bg-slate-700 rounded border border-slate-600 w-full"
                          />
                        )}
                        <input
                          type="text"
                          value={editReason}
                          onChange={(e) => setEditReason(e.target.value)}
                          placeholder="Reason for change (optional)"
                          className="px-2 py-1 bg-slate-700 rounded border border-slate-600 w-full text-sm"
                        />
                      </div>
                    ) : (
                      <div className="flex items-center gap-2">
                        <span className={param.is_overridden ? 'text-yellow-400 font-medium' : ''}>
                          {String(param.value)}
                        </span>
                        {param.is_overridden && (
                          <span className="px-2 py-0.5 bg-yellow-600/30 text-yellow-400 rounded text-xs">
                            Modified
                          </span>
                        )}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-gray-400">
                    {param.original_value !== undefined ? String(param.original_value) : '-'}
                  </td>
                  <td className="px-4 py-3">
                    <span className="px-2 py-1 bg-slate-700 rounded text-xs">
                      {param.constraints?.value_type || 'string'}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-400">
                    {param.constraints?.min_value !== undefined && (
                      <span>Min: {param.constraints.min_value} </span>
                    )}
                    {param.constraints?.max_value !== undefined && (
                      <span>Max: {param.constraints.max_value} </span>
                    )}
                    {param.constraints?.allowed_values && (
                      <span>Options: {param.constraints.allowed_values.join(', ')}</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {editingParam === param.name ? (
                      <div className="flex gap-2">
                        <button
                          onClick={() => handleSaveEdit(param)}
                          disabled={updateConfig.isPending}
                          className="px-3 py-1 bg-green-600 hover:bg-green-700 rounded text-sm disabled:opacity-50"
                        >
                          {updateConfig.isPending ? 'Saving...' : 'Save'}
                        </button>
                        <button
                          onClick={() => setEditingParam(null)}
                          className="px-3 py-1 bg-slate-600 hover:bg-slate-500 rounded text-sm"
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <div className="flex gap-2">
                        <button
                          onClick={() => handleStartEdit(param)}
                          className="px-3 py-1 bg-blue-600 hover:bg-blue-700 rounded text-sm"
                        >
                          Edit
                        </button>
                        {param.is_overridden && (
                          <button
                            onClick={() => handleReset(param.name)}
                            disabled={resetParameter.isPending}
                            className="px-3 py-1 bg-slate-600 hover:bg-slate-500 rounded text-sm disabled:opacity-50"
                          >
                            Reset
                          </button>
                        )}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Help Text */}
      <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
        <h3 className="font-medium mb-2">Configuration Help</h3>
        <ul className="text-sm text-gray-400 space-y-1">
          <li>• Modified parameters are highlighted in yellow and marked as "Modified"</li>
          <li>• Changes take effect immediately but do not persist across restarts</li>
          <li>• Use the "Reset" button to restore a parameter to its default value</li>
          <li>• Providing a reason helps track why changes were made</li>
        </ul>
      </div>

      {/* Error Display */}
      {updateConfig.isError && (
        <div className="bg-red-900/30 border border-red-600 rounded-lg p-4">
          <p className="text-red-400">
            Failed to update configuration: {(updateConfig.error as Error)?.message || 'Unknown error'}
          </p>
        </div>
      )}
    </div>
  )
}

export default Config
