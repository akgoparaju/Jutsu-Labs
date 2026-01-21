/**
 * StrategyContext - React context for multi-strategy selection and comparison
 *
 * Provides:
 * - Strategy list from API
 * - Selected strategy state
 * - Compare mode state
 * - Persistence in localStorage
 *
 * @version 1.0.0
 * @part Multi-Strategy UI - Phase 4
 */

import { createContext, useContext, useState, useEffect, ReactNode, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { strategiesApi, StrategyInfo } from '../api/client'
import {
  STRATEGY_COLORS,
  BASELINE_STYLE,
  MAX_COMPARE_STRATEGIES,
  getStrategyStyle,
  StrategyStyle,
} from '../constants/strategyColors'

const STORAGE_KEY = 'jutsu_selected_strategy'
const COMPARE_KEY = 'jutsu_compare_strategies'
const URL_STRATEGIES_PARAM = 'strategies'

interface StrategyContextType {
  // Strategy list
  strategies: StrategyInfo[]
  isLoading: boolean
  error: string | null

  // Selection state
  selectedStrategy: string
  setSelectedStrategy: (id: string) => void

  // Primary strategy info
  primaryStrategyId: string | null

  // Compare mode
  isCompareMode: boolean
  setCompareMode: (enabled: boolean) => void
  compareStrategies: string[]
  setCompareStrategies: (ids: string[]) => void
  toggleCompareStrategy: (id: string) => void

  // Alias for multi-strategy UI (compareStrategies)
  selectedStrategies: string[]

  // Helpers
  getStrategyById: (id: string) => StrategyInfo | undefined
  getStrategyDisplayName: (id: string) => string

  // Color mapping for multi-strategy comparison
  getColorForStrategy: (strategyId: string) => StrategyStyle
  getStyleForStrategyIndex: (index: number) => StrategyStyle
  baselineStyle: StrategyStyle
  maxCompareStrategies: number

  // URL sync
  updateUrlWithStrategies: () => void
  loadStrategiesFromUrl: () => string[] | null
}

const StrategyContext = createContext<StrategyContextType | null>(null)

export function StrategyProvider({ children }: { children: ReactNode }) {
  // Initialize from localStorage
  const [selectedStrategy, setSelectedStrategyState] = useState<string>(() => {
    return localStorage.getItem(STORAGE_KEY) || 'v3_5b'
  })

  const [isCompareMode, setCompareModeState] = useState(false)

  const [compareStrategies, setCompareStrategiesState] = useState<string[]>(() => {
    const stored = localStorage.getItem(COMPARE_KEY)
    if (stored) {
      try {
        return JSON.parse(stored)
      } catch {
        return []
      }
    }
    return []
  })

  // Fetch strategies from API
  const { data, isLoading, error } = useQuery({
    queryKey: ['strategies'],
    queryFn: () => strategiesApi.getStrategies({ active_only: true }).then(res => res.data),
    staleTime: 5 * 60 * 1000, // 5 minutes
    refetchOnWindowFocus: false,
  })

  const strategies = data?.strategies || []
  const primaryStrategyId = data?.primary_id || null

  // Persist selected strategy to localStorage
  const setSelectedStrategy = useCallback((id: string) => {
    setSelectedStrategyState(id)
    localStorage.setItem(STORAGE_KEY, id)
  }, [])

  // Persist compare mode state
  const setCompareMode = useCallback((enabled: boolean) => {
    setCompareModeState(enabled)
    if (!enabled) {
      // Clear compare strategies when disabling compare mode
      setCompareStrategiesState([])
      localStorage.removeItem(COMPARE_KEY)
    }
  }, [])

  // Persist compare strategies to localStorage
  const setCompareStrategies = useCallback((ids: string[]) => {
    setCompareStrategiesState(ids)
    localStorage.setItem(COMPARE_KEY, JSON.stringify(ids))
  }, [])

  // Toggle a strategy in compare list
  const toggleCompareStrategy = useCallback((id: string) => {
    setCompareStrategiesState(prev => {
      const newList = prev.includes(id)
        ? prev.filter(s => s !== id)
        : [...prev, id]
      localStorage.setItem(COMPARE_KEY, JSON.stringify(newList))
      return newList
    })
  }, [])

  // Helper: Get strategy by ID
  const getStrategyById = useCallback((id: string): StrategyInfo | undefined => {
    return strategies.find(s => s.id === id)
  }, [strategies])

  // Helper: Get display name for strategy
  const getStrategyDisplayName = useCallback((id: string): string => {
    const strategy = strategies.find(s => s.id === id)
    return strategy?.display_name || id
  }, [strategies])

  // Color mapping: Get style for a strategy based on its position in compareStrategies
  const getColorForStrategy = useCallback((strategyId: string): StrategyStyle => {
    const index = compareStrategies.indexOf(strategyId)
    return index === -1 ? STRATEGY_COLORS[0] : getStrategyStyle(index)
  }, [compareStrategies])

  // Get style by index directly
  const getStyleForStrategyIndex = useCallback((index: number): StrategyStyle => {
    return getStrategyStyle(index)
  }, [])

  // URL sync: Update URL with current strategy selection
  const updateUrlWithStrategies = useCallback(() => {
    if (compareStrategies.length === 0) return

    const params = new URLSearchParams(window.location.search)
    params.set(URL_STRATEGIES_PARAM, compareStrategies.join(','))
    const newUrl = `${window.location.pathname}?${params.toString()}`
    window.history.replaceState({}, '', newUrl)
  }, [compareStrategies])

  // URL sync: Load strategies from URL
  const loadStrategiesFromUrl = useCallback((): string[] | null => {
    const params = new URLSearchParams(window.location.search)
    const strategiesParam = params.get(URL_STRATEGIES_PARAM)

    if (!strategiesParam) return null

    // Parse and validate strategy IDs
    const strategyIds = strategiesParam.split(',').slice(0, MAX_COMPARE_STRATEGIES)
    const validIds = strategyIds.filter(id =>
      strategies.some(s => s.id === id)
    )

    return validIds.length > 0 ? validIds : null
  }, [strategies])

  // Initialize compare strategies from URL or with defaults
  useEffect(() => {
    if (strategies.length === 0) return

    // First, try to load from URL
    const urlStrategies = loadStrategiesFromUrl()
    if (urlStrategies && urlStrategies.length > 0) {
      // If URL has strategies, use them and enable compare mode if multiple
      setCompareStrategies(urlStrategies)
      if (urlStrategies.length > 1) {
        setCompareModeState(true)
      }
      return
    }

    // Otherwise, initialize with default (primary strategy) if empty
    if (compareStrategies.length === 0) {
      const defaultStrategy = primaryStrategyId || strategies[0]?.id || 'v3_5b'
      setCompareStrategies([defaultStrategy])
    }
  }, [strategies, loadStrategiesFromUrl, primaryStrategyId, compareStrategies.length, setCompareStrategies])

  // Sync URL when compare strategies change
  useEffect(() => {
    if (compareStrategies.length > 0) {
      updateUrlWithStrategies()
    }
  }, [compareStrategies, updateUrlWithStrategies])

  // Validate selected strategy exists
  useEffect(() => {
    if (strategies.length > 0 && !strategies.find(s => s.id === selectedStrategy)) {
      // Selected strategy not found, reset to primary or first available
      const defaultStrategy = primaryStrategyId || strategies[0]?.id || 'v3_5b'
      setSelectedStrategy(defaultStrategy)
    }
  }, [strategies, selectedStrategy, primaryStrategyId, setSelectedStrategy])

  const value: StrategyContextType = {
    strategies,
    isLoading,
    error: error ? (error as Error).message : null,
    selectedStrategy,
    setSelectedStrategy,
    primaryStrategyId,
    isCompareMode,
    setCompareMode,
    compareStrategies,
    setCompareStrategies,
    toggleCompareStrategy,
    // Alias for multi-strategy UI
    selectedStrategies: compareStrategies,
    getStrategyById,
    getStrategyDisplayName,
    // Color mapping
    getColorForStrategy,
    getStyleForStrategyIndex,
    baselineStyle: BASELINE_STYLE,
    maxCompareStrategies: MAX_COMPARE_STRATEGIES,
    // URL sync
    updateUrlWithStrategies,
    loadStrategiesFromUrl,
  }

  return (
    <StrategyContext.Provider value={value}>
      {children}
    </StrategyContext.Provider>
  )
}

export function useStrategy(): StrategyContextType {
  const context = useContext(StrategyContext)
  if (!context) {
    throw new Error('useStrategy must be used within a StrategyProvider')
  }
  return context
}

export default StrategyContext
