import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { statusApi, controlApi, indicatorsApi } from '../api/client'

// Status query
export function useStatus() {
  return useQuery({
    queryKey: ['status'],
    queryFn: () => statusApi.getStatus().then(res => res.data),
    refetchInterval: 5000, // Refresh every 5 seconds
  })
}

// Health check query
export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: () => statusApi.getHealth().then(res => res.data),
    refetchInterval: 30000, // Refresh every 30 seconds
  })
}

// Regime query
export function useRegime() {
  return useQuery({
    queryKey: ['regime'],
    queryFn: () => statusApi.getRegime().then(res => res.data),
    refetchInterval: 5000,
  })
}

// Indicators query
export function useIndicators() {
  return useQuery({
    queryKey: ['indicators'],
    queryFn: () => indicatorsApi.getIndicators().then(res => res.data),
    refetchInterval: 5000,
  })
}

// Engine state query
export function useEngineState() {
  return useQuery({
    queryKey: ['engineState'],
    queryFn: () => controlApi.getState().then(res => res.data),
    refetchInterval: 5000,
  })
}

// Control mutations
export function useStartEngine() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (params: { mode?: string; confirm?: boolean }) =>
      controlApi.start({ action: 'start', ...params }).then(res => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['status'] })
      queryClient.invalidateQueries({ queryKey: ['engineState'] })
    },
  })
}

export function useStopEngine() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () =>
      controlApi.stop({ action: 'stop' }).then(res => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['status'] })
      queryClient.invalidateQueries({ queryKey: ['engineState'] })
    },
  })
}

export function useSwitchMode() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (params: { mode: string; confirm?: boolean }) =>
      controlApi.switchMode({ action: 'mode_switch', ...params }).then(res => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['status'] })
      queryClient.invalidateQueries({ queryKey: ['engineState'] })
    },
  })
}
