import { useEffect, useRef, useState, useCallback } from 'react'
import { useQueryClient } from '@tanstack/react-query'

interface WebSocketMessage {
  type: string
  timestamp: string
  data?: unknown
  message?: string
}

interface UseWebSocketOptions {
  url?: string
  reconnectInterval?: number
  maxReconnectAttempts?: number
  onMessage?: (message: WebSocketMessage) => void
  onConnect?: () => void
  onDisconnect?: () => void
  onError?: (error: Event) => void
}

interface UseWebSocketReturn {
  isConnected: boolean
  lastMessage: WebSocketMessage | null
  sendMessage: (message: object) => void
  reconnect: () => void
}

export function useWebSocket(options: UseWebSocketOptions = {}): UseWebSocketReturn {
  const {
    url = `ws://${window.location.hostname}:8000/ws`,
    reconnectInterval = 3000,
    maxReconnectAttempts = 10,
    onMessage,
    onConnect,
    onDisconnect,
    onError,
  } = options

  const queryClient = useQueryClient()
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectAttemptsRef = useRef(0)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout>>()

  const [isConnected, setIsConnected] = useState(false)
  const [lastMessage, setLastMessage] = useState<WebSocketMessage | null>(null)

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return
    }

    try {
      wsRef.current = new WebSocket(url)

      wsRef.current.onopen = () => {
        console.log('WebSocket connected')
        setIsConnected(true)
        reconnectAttemptsRef.current = 0
        onConnect?.()

        // Send ping to keep connection alive
        const pingInterval = setInterval(() => {
          if (wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify({ type: 'ping' }))
          }
        }, 30000)

        // Clean up ping interval when connection closes
        wsRef.current!.onclose = () => {
          clearInterval(pingInterval)
          handleDisconnect()
        }
      }

      wsRef.current.onmessage = (event) => {
        try {
          const message: WebSocketMessage = JSON.parse(event.data)
          setLastMessage(message)
          onMessage?.(message)

          // Auto-invalidate relevant queries based on message type
          switch (message.type) {
            case 'status_update':
              queryClient.invalidateQueries({ queryKey: ['status'] })
              break
            case 'trade_executed':
              queryClient.invalidateQueries({ queryKey: ['trades'] })
              queryClient.invalidateQueries({ queryKey: ['tradeStats'] })
              queryClient.invalidateQueries({ queryKey: ['performance'] })
              break
            case 'regime_change':
              queryClient.invalidateQueries({ queryKey: ['regime'] })
              queryClient.invalidateQueries({ queryKey: ['status'] })
              break
          }
        } catch (error) {
          console.error('Failed to parse WebSocket message:', error)
        }
      }

      wsRef.current.onerror = (error) => {
        console.error('WebSocket error:', error)
        onError?.(error)
      }
    } catch (error) {
      console.error('Failed to create WebSocket:', error)
      scheduleReconnect()
    }
  }, [url, onConnect, onMessage, onError, queryClient])

  const handleDisconnect = useCallback(() => {
    console.log('WebSocket disconnected')
    setIsConnected(false)
    onDisconnect?.()
    scheduleReconnect()
  }, [onDisconnect])

  const scheduleReconnect = useCallback(() => {
    if (reconnectAttemptsRef.current >= maxReconnectAttempts) {
      console.log('Max reconnect attempts reached')
      return
    }

    // Clear any existing reconnect timeout
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
    }

    const delay = reconnectInterval * Math.pow(1.5, reconnectAttemptsRef.current)
    console.log(`Scheduling reconnect in ${delay}ms (attempt ${reconnectAttemptsRef.current + 1})`)

    reconnectTimeoutRef.current = setTimeout(() => {
      reconnectAttemptsRef.current++
      connect()
    }, delay)
  }, [connect, maxReconnectAttempts, reconnectInterval])

  const reconnect = useCallback(() => {
    // Force close existing connection
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }

    // Reset reconnect attempts
    reconnectAttemptsRef.current = 0

    // Clear any pending reconnect
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
    }

    // Connect immediately
    connect()
  }, [connect])

  const sendMessage = useCallback((message: object) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message))
    } else {
      console.warn('WebSocket not connected, message not sent')
    }
  }, [])

  // Connect on mount
  useEffect(() => {
    connect()

    return () => {
      // Clean up on unmount
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
      }
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, [connect])

  return {
    isConnected,
    lastMessage,
    sendMessage,
    reconnect,
  }
}

// Hook for auto-connecting WebSocket in the app
export function useLiveUpdates() {
  const { isConnected, lastMessage } = useWebSocket({
    onMessage: (message) => {
      // Log important events
      if (message.type === 'trade_executed') {
        console.log('Trade executed:', message.data)
      } else if (message.type === 'regime_change') {
        console.log('Regime changed:', message.data)
      } else if (message.type === 'error') {
        console.error('Server error:', message.message)
      }
    },
  })

  return {
    isConnected,
    lastMessage,
  }
}
