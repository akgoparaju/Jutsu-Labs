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
import { strategiesApi, StrategyInfo, StrategiesListResponse } from '../api/client'

const STORAGE_KEY = 'jutsu_selected_strategy'
const COMPARE_KEY = 'jutsu_compare_strategies'

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

  // Helpers
  getStrategyById: (id: string) => StrategyInfo | undefined
  getStrategyDisplayName: (id: string) => string
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

  // Initialize compare strategies with primary if empty and strategies loaded
  useEffect(() => {
    if (strategies.length > 0 && compareStrategies.length === 0 && isCompareMode) {
      // Default to first two strategies for comparison
      const defaultCompare = strategies.slice(0, 2).map(s => s.id)
      setCompareStrategies(defaultCompare)
    }
  }, [strategies, compareStrategies.length, isCompareMode, setCompareStrategies])

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
    getStrategyById,
    getStrategyDisplayName,
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
