/**
 * Reconcile open follow_up threads against the server objects they wait on.
 *
 * A follow_up such as "await synthesis of compound 12" can carry a ``link`` to
 * a run, a review item or a document. This reads the current server status
 * (read-only capability calls, no token needed) and updates the local thread:
 * a run that reached ``done`` closes its follow_up; a failed run, an undecided
 * review or a still-processing run is annotated and left open for the model to
 * act on. Storage stays in workState; this module only reads the server and
 * applies the resulting local updates.
 */

import { backendBaseUrl } from './capabilities.js'
import { errorMessage } from './text.js'
import { readWorkState, updateWorkThread, type WorkLink } from './workState.js'

const CHECK_TIMEOUT_MS = 8_000
//: Bound the review scan; an item beyond this page is reported, never closed.
const REVIEW_SCAN_LIMIT = 200

export interface ThreadCheckResult {
  id: string
  title: string
  link: WorkLink
  status: string
  outcome: 'closed' | 'open' | 'unreachable'
  note: string
}

interface LinkStatus {
  status: string
  note: string
  close: boolean
}

async function fetchCapability(
  name: string,
  payload: unknown,
): Promise<Record<string, unknown>> {
  const response = await fetch(
    `${backendBaseUrl()}/api/v1/capabilities/${name}`,
    {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(CHECK_TIMEOUT_MS),
    },
  )
  if (!response.ok) throw new Error(`${name} failed (${response.status})`)
  const body = (await response.json()) as {
    success?: boolean
    data?: Record<string, unknown>
  }
  if (!body.success) throw new Error(`${name} returned an error`)
  return body.data ?? {}
}

async function checkLink(link: WorkLink): Promise<LinkStatus> {
  if (link.kind === 'run') {
    const data = await fetchCapability('runs', {
      action: 'get',
      run_id: link.id,
    })
    const status = String(data.status ?? 'unknown')
    const note = `run ${link.id} is ${status}`
    // Only a successful run resolves the wait; a failure needs the model.
    return { status, note, close: status === 'done' }
  }
  if (link.kind === 'document') {
    const data = await fetchCapability('document_read', {
      part: 'info',
      doc_id: link.id,
    })
    const status = String(data.status ?? 'unknown')
    return { status, note: `document ${link.id} is ${status}`, close: false }
  }
  const data = await fetchCapability('list_review_queue', {
    status: null,
    kind: link.sub ?? null,
    limit: REVIEW_SCAN_LIMIT,
  })
  const items = Array.isArray(data.items) ? data.items : []
  const item = items.find(
    (row): row is Record<string, unknown> =>
      typeof row === 'object' &&
      row !== null &&
      (row as { item_id?: unknown }).item_id === link.id,
  )
  if (!item) {
    // Absence may just mean the item is beyond the scanned page; never close on it.
    return {
      status: 'not_found',
      note: `review ${link.id} not in first ${REVIEW_SCAN_LIMIT} items`,
      close: false,
    }
  }
  const status = String(item.status ?? 'pending')
  const decided = status === 'confirmed' || status === 'rejected'
  return { status, note: `review ${link.id} is ${status}`, close: decided }
}

/** Check every open linked follow_up; apply local updates and report each. */
export async function reconcileWorkThreads(): Promise<ThreadCheckResult[]> {
  const state = await readWorkState()
  const targets = state.threads.filter(
    (thread) =>
      thread.status === 'open' && thread.kind === 'follow_up' && thread.link,
  )
  const results: ThreadCheckResult[] = []
  for (const thread of targets) {
    const link = thread.link as WorkLink
    try {
      const { status, note, close } = await checkLink(link)
      await updateWorkThread(thread.id, {
        check_note: note,
        last_checked: new Date().toISOString(),
        ...(close ? { status: 'done' as const } : {}),
      })
      results.push({
        id: thread.id,
        title: thread.title,
        link,
        status,
        outcome: close ? 'closed' : 'open',
        note,
      })
    } catch (error) {
      results.push({
        id: thread.id,
        title: thread.title,
        link,
        status: 'unknown',
        outcome: 'unreachable',
        note: errorMessage(error),
      })
    }
  }
  return results
}
