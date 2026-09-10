/** Poll sidecar health status. */

import { useEffect } from 'react'
import { httpGet } from '../api/http/_utils'

export interface SidecarStatusEvent {
  healthy: boolean
  restartCount: number
  state: 'online' | 'offline'
  uptimeSecs: number
  lastError: string | null
}

export function useSidecarEvents() {
  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setInterval> | null = null

    const poll = async () => {
      if (cancelled) return
      try {
        await httpGet<{
          healthy: boolean
          restart_count: number
          state: string
          uptime_secs: number
          last_error: string | null
        }>('/api/v1/sidecar/status')
      } catch {
        // sidecar offline — silent in production
      }
    }

    void poll()
    timer = setInterval(poll, 30000)

    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [])
}
