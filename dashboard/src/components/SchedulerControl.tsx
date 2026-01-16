import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { controlApi, SchedulerStatus } from '../api/client'
import { ChevronDown, ChevronRight } from 'lucide-react'

/**
 * SchedulerControl Component
 *
 * Displays scheduler status and provides controls for:
 * - Enable/disable scheduler toggle
 * - Manual trigger (Run Now) button
 * - Next scheduled run time
 * - Last run status display
 *
 * Collapsible by default to reduce UI clutter.
 */
export function SchedulerControl() {
  const queryClient = useQueryClient()
  const [showConfirmTrigger, setShowConfirmTrigger] = useState(false)
  const [isExpanded, setIsExpanded] = useState(false)

  // Fetch scheduler status
  const { data: status, isLoading, error } = useQuery<SchedulerStatus>({
    queryKey: ['schedulerStatus'],
    queryFn: async () => {
      const response = await controlApi.getSchedulerStatus()
      return response.data
    },
    refetchInterval: 30000, // Refresh every 30 seconds
  })

  // Enable scheduler mutation
  const enableMutation = useMutation({
    mutationFn: () => controlApi.enableScheduler(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['schedulerStatus'] })
    },
  })

  // Disable scheduler mutation
  const disableMutation = useMutation({
    mutationFn: () => controlApi.disableScheduler(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['schedulerStatus'] })
    },
  })

  // Trigger scheduler mutation
  const triggerMutation = useMutation({
    mutationFn: () => controlApi.triggerScheduler(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['schedulerStatus'] })
      setShowConfirmTrigger(false)
    },
    onError: () => {
      setShowConfirmTrigger(false)
    },
  })

  // Handle toggle
  const handleToggle = () => {
    if (status?.enabled) {
      disableMutation.mutate()
    } else {
      enableMutation.mutate()
    }
  }

  // Handle trigger
  const handleTrigger = () => {
    if (!showConfirmTrigger) {
      setShowConfirmTrigger(true)
      return
    }
    triggerMutation.mutate()
  }

  // Format datetime for display
  const formatDateTime = (isoString: string | null | undefined) => {
    if (!isoString) return 'N/A'
    try {
      const date = new Date(isoString)
      return date.toLocaleString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
        hour12: true,
      })
    } catch {
      return isoString
    }
  }

  // Convert EST time string to local time display
  // Input: "09:45 AM EST" -> Output: "09:45 AM EST (6:45 AM PST)"
  const formatEstWithLocal = (estTimeStr: string | null | undefined) => {
    if (!estTimeStr) return 'N/A'
    try {
      // Parse the EST time (format: "HH:MM AM/PM EST")
      const match = estTimeStr.match(/(\d{1,2}):(\d{2})\s*(AM|PM)\s*EST/i)
      if (!match) return estTimeStr

      let hours = parseInt(match[1], 10)
      const minutes = parseInt(match[2], 10)
      const isPM = match[3].toUpperCase() === 'PM'

      // Convert to 24-hour format
      if (isPM && hours !== 12) hours += 12
      if (!isPM && hours === 12) hours = 0

      // Check if user is in Eastern timezone - no conversion needed
      const userTz = Intl.DateTimeFormat().resolvedOptions().timeZone
      if (userTz === 'America/New_York' || userTz.includes('Eastern')) {
        return estTimeStr
      }

      // Create a date in Eastern timezone for today
      const today = new Date()
      const dateStr = today.toLocaleDateString('en-CA') // YYYY-MM-DD format
      const timeStr = `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:00`

      // Create ISO string with Eastern timezone offset
      // EST = UTC-5, EDT = UTC-4. Use America/New_York to handle DST automatically
      const easternDate = new Date(`${dateStr}T${timeStr}-05:00`) // EST offset

      // Format in user's local timezone
      const localTime = easternDate.toLocaleString('en-US', {
        hour: 'numeric',
        minute: '2-digit',
        hour12: true,
        timeZoneName: 'short',
      })

      return `${estTimeStr} (${localTime})`
    } catch {
      return estTimeStr
    }
  }

  // Get status indicator color
  const getStatusColor = () => {
    if (status?.is_running) return 'bg-yellow-500 animate-pulse'
    if (status?.enabled) return 'bg-green-500'
    return 'bg-gray-500'
  }

  // Get status text
  const getStatusText = () => {
    if (status?.is_running) return 'Running'
    if (status?.enabled) return 'Enabled'
    return 'Disabled'
  }

  // Get last run status icon and color
  const getLastRunStatusDisplay = () => {
    switch (status?.last_run_status) {
      case 'success':
        return {
          icon: (
            <svg className="w-4 h-4 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          ),
          text: 'success',
          color: 'text-green-500',
        }
      case 'failed':
        return {
          icon: (
            <svg className="w-4 h-4 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          ),
          text: 'failed',
          color: 'text-red-500',
        }
      case 'skipped':
        return {
          icon: (
            <svg className="w-4 h-4 text-yellow-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
          ),
          text: 'skipped',
          color: 'text-yellow-500',
        }
      default:
        return {
          icon: null,
          text: 'N/A',
          color: 'text-gray-400',
        }
    }
  }

  const isToggling = enableMutation.isPending || disableMutation.isPending
  const isTriggering = triggerMutation.isPending

  if (isLoading) {
    return (
      <div className="bg-slate-800 rounded-lg p-6 border border-slate-700">
        <div className="flex items-center gap-3">
          <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-blue-400"></div>
          <span className="text-gray-400">Loading scheduler status...</span>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-slate-800 rounded-lg p-6 border border-slate-700">
        <div className="flex items-center gap-2 text-red-400">
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          <span>Failed to load scheduler status</span>
        </div>
      </div>
    )
  }

  const lastRunStatus = getLastRunStatusDisplay()

  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700">
      {/* Collapsible Header */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between p-4 hover:bg-slate-700/50 rounded-lg transition-colors"
      >
        <div className="flex items-center gap-2">
          <svg className="w-5 h-5 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
          </svg>
          <h3 className="text-lg font-semibold">Scheduler Control</h3>
          {/* Compact status indicator when collapsed */}
          {!isExpanded && (
            <div className="flex items-center gap-2 ml-4">
              <span className={`w-2 h-2 rounded-full ${getStatusColor()}`} />
              <span className="text-sm text-gray-400">{getStatusText()}</span>
              {status?.next_run && status?.enabled && (
                <span className="text-xs text-gray-500">
                  Next: {formatDateTime(status.next_run)}
                </span>
              )}
            </div>
          )}
        </div>
        {isExpanded ? (
          <ChevronDown className="w-5 h-5 text-gray-400" />
        ) : (
          <ChevronRight className="w-5 h-5 text-gray-400" />
        )}
      </button>

      {/* Collapsible Content */}
      {isExpanded && (
      <div className="px-6 pb-6 space-y-4">
        {/* Status Row with Toggle */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className={`w-3 h-3 rounded-full ${getStatusColor()}`} />
            <span className="font-medium">{getStatusText()}</span>
          </div>

          {/* Toggle Switch */}
          <button
            onClick={handleToggle}
            disabled={isToggling || status?.is_running}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-slate-800 ${
              status?.enabled ? 'bg-green-600' : 'bg-gray-600'
            } ${(isToggling || status?.is_running) ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
          >
            <span
              className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                status?.enabled ? 'translate-x-6' : 'translate-x-1'
              }`}
            />
          </button>
        </div>

        {/* Execution Time */}
        <div className="flex justify-between text-sm">
          <span className="text-gray-400">Execution Time:</span>
          <span className="font-medium">{formatEstWithLocal(status?.execution_time_est)}</span>
        </div>

        {/* Next Run */}
        <div className="flex justify-between text-sm">
          <span className="text-gray-400">Next Run:</span>
          <span className="font-medium">
            {status?.enabled ? formatDateTime(status?.next_run) : 'Disabled'}
          </span>
        </div>

        {/* Last Run */}
        <div className="flex justify-between text-sm">
          <span className="text-gray-400">Last Run:</span>
          <div className="flex items-center gap-2">
            <span className="font-medium">{formatDateTime(status?.last_run)}</span>
            {lastRunStatus.icon && (
              <span className="flex items-center gap-1">
                {lastRunStatus.icon}
                <span className={`text-xs ${lastRunStatus.color}`}>{lastRunStatus.text}</span>
              </span>
            )}
          </div>
        </div>

        {/* Run Count */}
        <div className="flex justify-between text-sm">
          <span className="text-gray-400">Total Runs:</span>
          <span className="font-medium">{status?.run_count ?? 0}</span>
        </div>

        {/* Last Error (if any) */}
        {status?.last_error && (
          <div className="bg-red-900/30 border border-red-600/50 rounded-lg p-3 mt-2">
            <div className="text-red-400 text-sm">
              <span className="font-medium">Last Error: </span>
              {status.last_error}
            </div>
          </div>
        )}

        {/* Run Now Button */}
        <div className="pt-2">
          {!showConfirmTrigger ? (
            <button
              onClick={handleTrigger}
              disabled={isTriggering || status?.is_running}
              className={`w-full flex items-center justify-center gap-2 px-4 py-2 rounded-lg font-medium transition-colors ${
                (isTriggering || status?.is_running)
                  ? 'bg-slate-700 text-gray-400 cursor-not-allowed'
                  : 'bg-blue-600 hover:bg-blue-700 text-white'
              }`}
            >
              {isTriggering ? (
                <>
                  <div className="animate-spin rounded-full h-4 w-4 border-2 border-white border-t-transparent"></div>
                  <span>Triggering...</span>
                </>
              ) : status?.is_running ? (
                <>
                  <div className="animate-spin rounded-full h-4 w-4 border-2 border-gray-400 border-t-transparent"></div>
                  <span>Running...</span>
                </>
              ) : (
                <>
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  <span>Run Now</span>
                </>
              )}
            </button>
          ) : (
            <div className="space-y-2">
              <p className="text-yellow-400 text-sm text-center">
                This will execute the strategy immediately. Continue?
              </p>
              <div className="flex gap-2">
                <button
                  onClick={() => setShowConfirmTrigger(false)}
                  className="flex-1 px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg font-medium transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleTrigger}
                  disabled={isTriggering}
                  className="flex-1 px-4 py-2 bg-yellow-600 hover:bg-yellow-700 rounded-lg font-medium transition-colors"
                >
                  {isTriggering ? 'Triggering...' : 'Confirm'}
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Mutation Error Display */}
        {(enableMutation.error || disableMutation.error || triggerMutation.error) && (
          <div className="bg-red-900/30 border border-red-600/50 rounded-lg p-3">
            <div className="text-red-400 text-sm">
              {(enableMutation.error as any)?.response?.data?.detail ||
                (disableMutation.error as any)?.response?.data?.detail ||
                (triggerMutation.error as any)?.response?.data?.detail ||
                'An error occurred'}
            </div>
          </div>
        )}
      </div>
      )}
    </div>
  )
}

export default SchedulerControl
