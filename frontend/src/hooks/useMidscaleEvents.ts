import { useEffect, useRef, useCallback } from 'react'
import { useAuth } from './useAuth'

type EventHandler = (event: Record<string, unknown>) => void

interface UseMidscaleEventsOptions {
  onConfigChanged?: EventHandler
  onDeviceEnrolled?: EventHandler
  onDeviceRevoked?: EventHandler
  onEndpointReported?: EventHandler
  onRelayFallback?: EventHandler
  onNatPunchSucceeded?: EventHandler
  onNatPunchFailed?: EventHandler
  pollingInterval?: number
}

export function useMidscaleEvents(options: UseMidscaleEventsOptions = {}) {
  const { token } = useAuth()
  const wsRef = useRef<WebSocket | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const handlersRef = useRef(options)

  handlersRef.current = options

  const handleEvent = useCallback((event: Record<string, unknown>) => {
    const type = event.type as string
    const h = handlersRef.current

    switch (type) {
      case 'config.changed': h.onConfigChanged?.(event); break
      case 'device.enrolled': h.onDeviceEnrolled?.(event); break
      case 'device.revoked': h.onDeviceRevoked?.(event); break
      case 'endpoint.reported': h.onEndpointReported?.(event); break
      case 'relay.fallback': h.onRelayFallback?.(event); break
      case 'nat.punch_succeeded': h.onNatPunchSucceeded?.(event); break
      case 'nat.punch_failed': h.onNatPunchFailed?.(event); break
    }
  }, [])

  useEffect(() => {
    if (!token) return

    const pollingInterval = options.pollingInterval || 15000

    const connectWs = () => {
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const host = window.location.host
      const url = `${proto}//${host}/api/v1/ws/events?token=${token}`
      try {
        const ws = new WebSocket(url)
        ws.onmessage = (msg) => {
          try {
            const data = JSON.parse(msg.data)
            handleEvent(data)
          } catch { /* ignore parse errors */ }
        }
        ws.onclose = () => {
          wsRef.current = null
        }
        wsRef.current = ws
      } catch {
        wsRef.current = null
      }
    }

    connectWs()

    intervalRef.current = setInterval(() => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
        fetch('/api/v1/events/poll?since=' + Date.now(), {
          headers: { Authorization: `Bearer ${token}` },
        }).then(r => r.json()).then(events => {
          if (Array.isArray(events)) {
            events.forEach(handleEvent)
          }
        }).catch(() => {})
      }
    }, pollingInterval)

    return () => {
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
    }
  }, [token, handleEvent, options.pollingInterval])
}
