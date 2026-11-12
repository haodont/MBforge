import { clearTimeout, setTimeout as nodeSetTimeout } from 'node:timers'

import type { ExtensionAPI } from '@earendil-works/pi-coding-agent'

import { backendBaseUrl } from './capabilities.js'

/** Queue statuses that end a run; mirrors `foundation/queue_contract.py`. */
export const TERMINAL_RUN_STATUSES: Readonly<Record<string, true>> = {
  done: true,
  failed: true,
  cancelled: true,
}

const DEFAULT_INTERVAL_MS = 4_000
//: ~2 minutes of backend outage at the default interval, then the watcher
//: gives up; a deleted run (404) stops immediately.
const DEFAULT_MAX_FAILURES = 30
//: A poll that never answers must not wedge the watcher: the next poll is only
//: scheduled after this one settles, so a hung fetch would stop it forever.
const DEFAULT_TIMEOUT_MS = 10_000

export interface RunWatcherOptions {
  intervalMs?: number
  maxFailures?: number
  timeoutMs?: number
  fetchImpl?: typeof fetch
}

export interface RunWatcher {
  /** Poll until *runId* reaches a terminal status, then report it once. */
  watch(runId: string): void
  /** Cancel every outstanding poll (session shutdown). */
  stopAll(): void
}

/** One finished run, already formatted for the session transcript. */
export interface RunCompletion {
  runId: string
  status: string
  docId: string
  message: string
}

interface RunSnapshot {
  status?: unknown
  doc_id?: unknown
  nodes?: unknown
}

interface RunNode {
  stage?: unknown
  status?: unknown
  error?: unknown
}

function runCompletion(runId: string, snapshot: RunSnapshot): RunCompletion {
  const status = typeof snapshot.status === 'string' ? snapshot.status : 'unknown'
  const docId =
    typeof snapshot.doc_id === 'string' && snapshot.doc_id !== ''
      ? snapshot.doc_id
      : 'unknown'
  const nodes = Array.isArray(snapshot.nodes)
    ? snapshot.nodes.filter(
        (node): node is RunNode => typeof node === 'object' && node !== null,
      )
    : []
  const stages = nodes
    .map((node) => `${String(node.stage ?? '?')}=${String(node.status ?? '?')}`)
    .join(', ')
  const failures = nodes
    .filter((node) => String(node.status ?? '') === 'failed')
    .map((node) => {
      const error = typeof node.error === 'string' ? node.error.trim() : ''
      const stage = String(node.stage ?? '?')
      return error === '' ? `${stage}: failed` : `${stage}: ${error.slice(0, 400)}`
    })
  const lines = [
    `MBForge run ${runId} finished with status "${status}" (document ${docId}).`,
    stages === '' ? '' : `Stages: ${stages}.`,
    failures.length === 0 ? '' : `Failures: ${failures.join(' | ')}`,
    status === 'done'
      ? 'Call runs with action="get" for the node details, then continue the task; Patent analysis is a separate submit_patent_analysis run.'
      : 'Inspect the failure, correct the cause, then call run_control with action="retry"; runs(action="get") carries the full node error.',
  ].filter((line) => line !== '')
  return { runId, status, docId, message: lines.join('\n') }
}

/**
 * Watch enqueued pipeline runs and report each one's terminal status once.
 *
 * ``submit_extraction``/``reingest_document``/``submit_patent_analysis`` (and
 * ``import_pdf``, which auto-enqueues) return run ids but no completion
 * signal. This watcher polls the read-only ``runs`` capability; the caller
 * decides when and how to surface the completion to the session.
 *
 * Polling is detached from the agent loop: timers are unref'd so they never
 * keep the CLI process alive, and ``stopAll`` runs on session shutdown. Only
 * runs passed to ``watch`` in this process are reported; a closed CLI has no
 * watcher and nothing is persisted for the next session.
 */
export function createRunWatcher(
  onFinished: (completion: RunCompletion) => void,
  options: RunWatcherOptions = {},
): RunWatcher {
  const intervalMs = options.intervalMs ?? DEFAULT_INTERVAL_MS
  const maxFailures = options.maxFailures ?? DEFAULT_MAX_FAILURES
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS
  const fetchImpl = options.fetchImpl ?? fetch
  const timers = new Map<string, NodeJS.Timeout>()
  const failures = new Map<string, number>()
  const active = new Set<string>()
  let stopped = false

  const forget = (runId: string): void => {
    active.delete(runId)
    failures.delete(runId)
    clearTimeout(timers.get(runId))
    timers.delete(runId)
  }

  const schedule = (runId: string): void => {
    if (stopped || !active.has(runId)) return
    const timer = nodeSetTimeout(() => {
      timers.delete(runId)
      void poll(runId)
    }, intervalMs)
    timer.unref()
    timers.set(runId, timer)
  }

  const poll = async (runId: string): Promise<void> => {
    if (stopped || !active.has(runId)) return
    try {
      const response = await fetchImpl(
        `${backendBaseUrl()}/api/v1/capabilities/runs`,
        {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ action: 'get', run_id: runId }),
          signal: AbortSignal.timeout(timeoutMs),
        },
      )
      if (response.status === 404) {
        // The run row is gone (deleted or cleaned up); no notification.
        forget(runId)
        return
      }
      if (!response.ok) {
        throw new Error(`runs failed (${response.status})`)
      }
      const payload = (await response.json()) as {
        success?: boolean
        data?: RunSnapshot
      }
      if (!payload.success) throw new Error('runs returned an error')
      const status = payload.data?.status
      if (
        typeof status === 'string' &&
        Object.hasOwn(TERMINAL_RUN_STATUSES, status)
      ) {
        forget(runId)
        onFinished(runCompletion(runId, payload.data ?? {}))
        return
      }
      failures.delete(runId)
    } catch {
      const count = (failures.get(runId) ?? 0) + 1
      if (count >= maxFailures) {
        forget(runId)
        return
      }
      failures.set(runId, count)
    }
    schedule(runId)
  }

  return {
    watch(runId: string): void {
      if (stopped || runId === '' || active.has(runId)) return
      active.add(runId)
      // The row exists as soon as the capability returned, so poll at once;
      // later checks are spaced by intervalMs.
      void poll(runId)
    },
    stopAll(): void {
      stopped = true
      for (const timer of timers.values()) {
        clearTimeout(timer)
      }
      timers.clear()
      failures.clear()
      active.clear()
    },
  }
}

/**
 * Deliver run completions to the session without using pi's message queues.
 *
 * pi's ``sendMessage(..., { deliverAs: "followUp" })`` queues the message while
 * the agent is streaming; that queue is re-delivered on session resume, so a
 * run that finished hours ago could wake the agent again. This notifier never
 * queues: it sends only when the session is idle (a plain ``triggerTurn``
 * append, which starts one turn and persists exactly once), and otherwise
 * holds completions in process memory until the next ``agent_settled``.
 * Pending completions die with the process, so a resumed session cannot replay
 * them. Each run id is delivered at most once per process.
 */
export interface RunNotifier {
  notify(completion: RunCompletion): void
  markBusy(): void
  markIdle(): void
  stop(): void
}

export function createRunNotifier(
  pi: Pick<ExtensionAPI, 'sendMessage'>,
): RunNotifier {
  const seen = new Set<string>()
  const pending = new Map<string, RunCompletion>()
  let busy = false
  let stopped = false

  const deliver = (items: RunCompletion[]): void => {
    // Mark busy before sending: the first message starts a turn, and any
    // completion racing in between must wait for the next settle.
    busy = true
    pi.sendMessage(
      {
        customType: 'mbforge.run',
        content: items.map((item) => item.message).join('\n\n'),
        display: true,
        details: {
          runs: items.map(({ runId, status, docId }) => ({
            runId,
            status,
            docId,
          })),
        },
      },
      // No deliverAs: if the session is idle this appends once and starts a
      // turn; if it is somehow still streaming, pi only steers the live run
      // and never writes the message to a resumable queue.
      { triggerTurn: true },
    )
  }

  return {
    notify(completion: RunCompletion): void {
      if (stopped || seen.has(completion.runId)) return
      seen.add(completion.runId)
      if (busy) {
        pending.set(completion.runId, completion)
        return
      }
      deliver([completion])
    },
    markBusy(): void {
      busy = true
    },
    markIdle(): void {
      if (stopped) return
      busy = false
      if (pending.size === 0) return
      const items = [...pending.values()]
      pending.clear()
      deliver(items)
    },
    stop(): void {
      stopped = true
      pending.clear()
    },
  }
}
