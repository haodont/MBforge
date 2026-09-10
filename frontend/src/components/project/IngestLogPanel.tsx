import { useEffect, useRef } from 'react'
import type { IngestLogEvent } from '@/api/http/ingest_queue'

interface IngestLogPanelProps {
  logs: IngestLogEvent[]
}

function formatTime(tsMs: number): string {
  const d = new Date(tsMs)
  return d.toLocaleTimeString([], { hour12: false })
}

function levelClass(level: string): string {
  switch (level.toLowerCase()) {
    case 'error':
      return 'is-error'
    case 'warn':
    case 'warning':
      return 'is-warn'
    case 'info':
    default:
      return 'is-info'
  }
}

export default function IngestLogPanel({ logs }: IngestLogPanelProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
  }, [logs])

  if (logs.length === 0) {
    return (
      <div className="ingest-log-panel is-empty">
        暂无日志，处理开始后将在此显示。
      </div>
    )
  }

  return (
    <div ref={containerRef} className="ingest-log-panel">
      {logs.map((log, index) => (
        <div key={`${log.ts_ms}-${index}`} className="ingest-log-row">
          <span className="ingest-log-time">{formatTime(log.ts_ms)}</span>
          <span className="ingest-log-stage">{log.stage}</span>
          <span className={`ingest-log-level ${levelClass(log.level)}`}>{log.level.toUpperCase()}</span>
          <span className="ingest-log-message">{log.message}</span>
        </div>
      ))}
    </div>
  )
}
