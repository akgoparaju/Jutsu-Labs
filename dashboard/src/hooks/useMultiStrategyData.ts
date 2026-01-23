/**
 * useMultiStrategyData - Hook for fetching data for multiple strategies in parallel
 *
 * Uses React Query's useQueries to efficiently fetch data for comparison views.
 * Handles loading states, errors, and data aggregation.
 *
 * @version 1.0.0
 * @part Multi-Strategy Comparison UI
 */

import { useQueries } from '@tanstack/react-query'
import { backtestApi, performanceApi, BacktestDataResponse, PerformanceResponse } from '../api/client'

/**
 * Result structure for multi-strategy data
 */
export interface MultiStrategyResult<T> {
  /** Data keyed by strategy ID */
  data: Record<string, T | undefined>
  /** True if any query is loading */
  isLoading: boolean
  /** True if any query has error */
  isError: boolean
  /** Array of error messages */
  errors: string[]
  /** Map of strategy ID to loading state */
  loadingStates: Record<string, boolean>
}

/**
 * Generic hook for fetching data for multiple strategies
 *
 * @param queryKeyBase Base key for query cache
 * @param fetchFn Function to fetch data for a single strategy
 * @param strategyIds Array of strategy IDs to fetch
 * @param enabled Whether to run the queries
 */
export function useMultiStrategyData<T>(
  queryKeyBase: string,
  fetchFn: (strategyId: string) => Promise<T>,
  strategyIds: string[],
  enabled = true
): MultiStrategyResult<T> {
  const queries = useQueries({
    queries: strategyIds.map((id) => ({
      queryKey: [queryKeyBase, id],
      queryFn: () => fetchFn(id),
      enabled,
      staleTime: 5 * 60 * 1000, // 5 minutes - data refreshed via WebSocket push
      refetchOnWindowFocus: false,
    })),
  })

  // Build result object
  const data: Record<string, T | undefined> = {}
  const loadingStates: Record<string, boolean> = {}
  const errors: string[] = []

  queries.forEach((query, index) => {
    const strategyId = strategyIds[index]
    data[strategyId] = query.data
    loadingStates[strategyId] = query.isLoading

    if (query.error) {
      errors.push(`${strategyId}: ${(query.error as Error).message}`)
    }
  })

  return {
    data,
    isLoading: queries.some((q) => q.isLoading),
    isError: queries.some((q) => q.isError),
    errors,
    loadingStates,
  }
}

/**
 * Hook for fetching backtest data for multiple strategies
 */
export function useMultiStrategyBacktestData(
  strategyIds: string[],
  params?: { start_date?: string; end_date?: string },
  enabled = true
): MultiStrategyResult<BacktestDataResponse> {
  const fetchFn = async (strategyId: string): Promise<BacktestDataResponse> => {
    const response = await backtestApi.getData({
      strategy_id: strategyId,
      start_date: params?.start_date,
      end_date: params?.end_date,
    })
    return response.data
  }

  // Include params in query key for cache busting on date changes
  const queryKey = params?.start_date || params?.end_date
    ? `backtest-data-${params.start_date}-${params.end_date}`
    : 'backtest-data'

  return useMultiStrategyData(queryKey, fetchFn, strategyIds, enabled)
}

/**
 * Hook for fetching performance data for multiple strategies
 */
export function useMultiStrategyPerformanceData(
  strategyIds: string[],
  params?: { mode?: string; days?: number; start_date?: string },
  enabled = true
): MultiStrategyResult<PerformanceResponse> {
  const fetchFn = async (strategyId: string): Promise<PerformanceResponse> => {
    const response = await performanceApi.getPerformance({
      strategy_id: strategyId,
      mode: params?.mode,
      days: params?.days,
      start_date: params?.start_date,
    })
    return response.data
  }

  // Include params in query key for cache busting
  const queryKey = `performance-data-${params?.mode}-${params?.days}-${params?.start_date}`

  return useMultiStrategyData(queryKey, fetchFn, strategyIds, enabled)
}

/**
 * Extract a specific metric from multi-strategy data for comparison
 */
export function extractMetricFromMultiData<T, V>(
  multiData: MultiStrategyResult<T>,
  strategyIds: string[],
  extractor: (data: T) => V
): Record<string, V | undefined> {
  const result: Record<string, V | undefined> = {}

  strategyIds.forEach((id) => {
    const data = multiData.data[id]
    if (data) {
      result[id] = extractor(data)
    }
  })

  return result
}

/**
 * Find the best value among strategies for a given metric
 * Returns the strategy ID with the best value
 */
export function findBestStrategy(
  values: Record<string, number | undefined>,
  higherIsBetter = true
): string | null {
  let bestId: string | null = null
  let bestValue: number | null = null

  Object.entries(values).forEach(([id, value]) => {
    if (value === undefined) return

    if (bestValue === null) {
      bestId = id
      bestValue = value
    } else if (higherIsBetter ? value > bestValue : value < bestValue) {
      bestId = id
      bestValue = value
    }
  })

  return bestId
}
