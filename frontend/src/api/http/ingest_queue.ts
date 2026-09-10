/** Ingest queue — 文档处理队列操作 via HTTP. */

import { httpPost, httpGet, invokeWithError, apiUrl } from './_utils'
import { ErrorCode } from '@/utils/errors'
import { logger } from '@/utils/logger'

export type IngestStageStatus = 'pending' | 'running' | 'success' | 'error'

export interface IngestTask {
  id: string
  file_path: string
  doc_id: string
  status: 'pending' | 'processing' | 'done' | 'failed' | 'cancelled'
  stage: string
  retry_count: number
  error: string | null
  file_size_bytes: number | null
  started_at: number | null
  created_at: number
  updated_at: number
  priority: number
  stage_statuses: Record<string, IngestStageStatus>
}

export interface QueueStats {
  total: number
  pending?: number
  processing?: number
  done?: number
  failed?: number
  cancelled?: number
  avg_stage_durations_ms?: number[]
  by_status?: Record<string, number>
}

export interface IngestQueueUpdateEvent {
  doc_id: string
  stage: string
  stats: QueueStats
}

export interface IngestWorkerHeartbeatEvent {
  library_root: string
  ts: number
  alive: boolean
}

export interface IngestLogEvent {
  doc_id: string
  stage: string
  /** "info" | "warn" | "error" */
  level: string
  message: string
  /** Unix epoch milliseconds */
  ts_ms: number
  /** 关联 task id（仅 DB 落库通道携带） */
  task_id?: string | null
}

/** DB 落库通道的日志行（与 IngestLogEvent 同构）。 */
export type IngestLogRecord = IngestLogEvent

interface IngestLogsResponse {
  logs?: IngestLogRecord[] | null
}

/** Track C: 嵌入阶段子进度事件 */
export interface IngestEmbedEvent {
  doc_id: string
  action: 'start' | 'done' | 'failed' | 'skipped'
  model: string
  progress: number
  error?: string
}

/** Pipeline SSE event payload (error/warning/info etc.). */
export interface IngestPipelineEvent {
  stage: string
  event: string
  message: string
  ts_ms: number
  data?: Record<string, unknown>
}

export interface IngestEventHandlers {
  onEvent?: (event: IngestPipelineEvent) => void
  onError?: (error: Event) => void
  onClose?: () => void
}

/**
 * Subscribe to real-time pipeline events for a single task via SSE.
 *
 * The SSE event name is the level (error/warning/info). The returned `close()`
 * must be called on unmount to release the EventSource. On `onerror` we do not
 * close the connection so the browser can auto-reconnect.
 */
export function subscribeIngestEvents(
  libraryRoot: string,
  taskId: string,
  handlers: IngestEventHandlers,
): { close: () => void } {
  const url = apiUrl(`/api/v1/pipeline/events/${encodeURIComponent(taskId)}?library_root=${encodeURIComponent(libraryRoot)}`)
  const es = new EventSource(url)

  const handleNamedEvent = (level: string, raw: MessageEvent) => {
    try {
      const parsed = JSON.parse(String(raw.data)) as IngestPipelineEvent
      handlers.onEvent?.(parsed)
    } catch {
      handlers.onEvent?.({
        stage: '',
        event: level,
        message: String(raw.data),
        ts_ms: Date.now(),
      })
    }
  }

  // SSE event names are the level values emitted by the backend.
  const levels = ['warning', 'info', 'debug'] as const
  levels.forEach((level) => {
    es.addEventListener(level, (raw) => handleNamedEvent(level, raw))
  })

  // `error` named events must be distinguished from native EventSource errors.
  // A backend `event: error` message arrives as a MessageEvent with data,
  // whereas a native connection error is a plain Event with no data.
  es.addEventListener('error', (raw) => {
    if (raw instanceof MessageEvent && raw.data !== '') {
      handleNamedEvent('error', raw)
      return
    }
    logger.error('[subscribeIngestEvents] SSE error:', raw)
    handlers.onError?.(raw)
  })

  // Fallback for unnamed/default messages.
  es.onmessage = (raw) => handleNamedEvent(raw.type || 'message', raw)

  es.onerror = (err) => {
    logger.error('[subscribeIngestEvents] SSE error:', err)
    handlers.onError?.(err)
    // Intentionally do not close; allow browser-level auto-reconnect.
  }

  return {
    close: () => {
      es.close()
      handlers.onClose?.()
    },
  }
}

interface IngestListResponse {
  tasks: IngestTask[]
}

export async function ingestList(libraryRoot: string): Promise<IngestTask[]> {
  return invokeWithError(
    () => httpPost<IngestListResponse>('/api/v1/pipeline/queue', { library_root: libraryRoot })
      .then((r) => Array.isArray(r.tasks) ? r.tasks : []),
    ErrorCode.ApiError,
  )
}

interface IngestStatsResponse {
  stats: QueueStats
}

export async function ingestStats(libraryRoot: string): Promise<QueueStats> {
  return invokeWithError(
    () => httpPost<IngestStatsResponse>('/api/v1/pipeline/queue/stats', { library_root: libraryRoot })
      .then((r) => r.stats),
    ErrorCode.ApiError,
  )
}

export async function ingestWorkerStatus(): Promise<{ status: string; ts: number }> {
  try {
    return await httpGet<{ status: string; ts: number }>('/api/v1/pipeline/worker/status')
  } catch {
    return { status: 'offline', ts: 0 }
  }
}

/** 获取某 doc_id 的最近 N 条 ingest 日志（DB 兜底通道）。
 *  默认 limit=500；可按需调小。 */
export async function ingestGetLogs(
  libraryRoot: string,
  docId: string,
  limit?: number,
): Promise<IngestLogRecord[]> {
  return invokeWithError(
    () =>
      httpPost<IngestLogsResponse>('/api/v1/pipeline/queue/logs', {
        library_root: libraryRoot,
        doc_id: docId,
        limit,
      }).then((response) => (Array.isArray(response.logs) ? response.logs : [])),
    ErrorCode.ApiError,
  )
}

export async function ingestCancel(libraryRoot: string, taskId: string): Promise<void> {
  return invokeWithError(
    async () => {
      await httpPost(`/api/v1/pipeline/queue/${taskId}/cancel`, { library_root: libraryRoot })
    },
    ErrorCode.ApiError,
  )
}

export async function ingestRetry(
  libraryRoot: string,
  taskId: string,
  resumeFromStage?: string,
): Promise<boolean> {
  return invokeWithError(
    () => httpPost<{ updated: number; error?: string | null }>(`/api/v1/pipeline/queue/${taskId}/retry`, {
      library_root: libraryRoot,
      task_ids: [taskId],
      resume_from_stage: resumeFromStage ?? null,
    })
      .then((response) => response.updated > 0),
    ErrorCode.ApiError,
  )
}

export async function ingestCleanup(libraryRoot: string): Promise<number> {
  return invokeWithError(
    () => httpPost<{ cleaned?: number }>('/api/v1/pipeline/queue/cleanup', { library_root: libraryRoot })
      .then((response) => response.cleaned ?? 0),
    ErrorCode.ApiError,
  )
}

export interface IngestBulkActionResult {
  updated: number
  skipped: number
}

export async function ingestCancelBatch(
  libraryRoot: string,
  taskIds: string[],
): Promise<IngestBulkActionResult> {
  return invokeWithError(
    () => httpPost<IngestBulkActionResult>('/api/v1/pipeline/queue/batch/cancel', {
      library_root: libraryRoot,
      task_ids: taskIds,
    }),
    ErrorCode.ApiError,
  )
}

export async function ingestRetryBatch(
  libraryRoot: string,
  taskIds: string[],
): Promise<IngestBulkActionResult> {
  return invokeWithError(
    () => httpPost<IngestBulkActionResult>('/api/v1/pipeline/queue/batch/retry', {
      library_root: libraryRoot,
      task_ids: taskIds,
    }),
    ErrorCode.ApiError,
  )
}

/** 手动将 PDF 加入处理队列。返回任务 ID。
 *
 * `force=true` 跳过同 hash 幂等检查 — 用于对已处理文件强制重新入队，
 * 新建任务而不复用现有 done 任务（保留历史记录）。
 */
export async function ingestEnqueue(
  libraryRoot: string,
  filePath: string,
  docId: string,
  force?: boolean,
): Promise<string> {
  return invokeWithError(
    () => httpPost<string>('/api/v1/pipeline/enqueue', {
      library_root: libraryRoot,
      file_path: filePath,
      doc_id: docId,
      force: force ?? false,
    }),
    ErrorCode.ApiError,
  )
}

/** 当前会话内用户主动触发的 doc_id 集合，用于跨页 toast 去噪。 */
const selfTriggeredDocs = new Set<string>()

export function trackSelfTriggeredDoc(docId: string): void {
  selfTriggeredDocs.add(docId)
  // 避免集合无限增长：超过 100 时清理最旧的 50 个。
  if (selfTriggeredDocs.size > 100) {
    const iter = selfTriggeredDocs.values()
    for (let i = 0; i < 50; i++) {
      const value = iter.next().value
      if (value !== undefined) selfTriggeredDocs.delete(value)
    }
  }
}

export function isSelfTriggeredDoc(docId: string): boolean {
  return selfTriggeredDocs.has(docId)
}

export function removeSelfTriggeredDoc(docId: string): void {
  selfTriggeredDocs.delete(docId)
}

export async function ingestSetPriority(
  libraryRoot: string,
  taskId: string,
  priority: number,
): Promise<void> {
  return invokeWithError(
    async () => {
      await httpPost(`/api/v1/pipeline/queue/${taskId}/priority`, {
        library_root: libraryRoot,
        priority,
      })
    },
    ErrorCode.ApiError,
  )
}

export async function ingestDeleteTask(
  libraryRoot: string,
  taskId: string,
): Promise<boolean> {
  const resp = await invokeWithError(
    () => httpPost<{ updated: number }>(`/api/v1/pipeline/queue/${taskId}/delete`, {
      library_root: libraryRoot,
    }),
    ErrorCode.ApiError,
  )
  return resp.updated > 0
}
