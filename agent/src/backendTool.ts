import type { ChildProcess } from 'node:child_process'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  defineTool,
  type ExtensionAPI,
  type ExtensionToolContext,
} from '@earendil-works/pi-coding-agent'
import { Type } from 'typebox'

import {
  backendAddress,
  clearBackendRecord,
  probeBackend,
  startBackend,
  stopBackend,
  stopRecordedBackend,
  type BackendAddress,
  type StopBackendResult,
} from './backendControl.js'
import { toolRenderers } from './toolRender.js'

export const BACKEND_TOOL_NAME = 'backend_control'
export const BACKEND_TOOL_NAMES = [BACKEND_TOOL_NAME] as const

const agentRoot = dirname(dirname(fileURLToPath(import.meta.url)))
const repoRoot = dirname(agentRoot)

/** Backend this session started through the tool; the launcher cannot see it. */
let startedHere: ChildProcess | null = null
process.once('exit', () => {
  if (!startedHere) return
  stopBackend(startedHere)
  clearBackendRecord(agentHome())
})

function agentHome(): string {
  return process.env.PI_CODING_AGENT_DIR ?? join(agentRoot, '.pi-agent')
}

const actionSchema = Type.Union(
  [Type.Literal('start'), Type.Literal('stop'), Type.Literal('restart')],
  {
    description:
      'start: launch the backend when nothing answers; stop: stop the backend this CLI started; restart: stop then start.',
  },
)

const parameters = Type.Object({ action: actionSchema })

export interface BackendToolReport {
  action: 'start' | 'stop' | 'restart'
  status: 'running' | 'stopped'
  base_url: string
  changed: boolean
  pid?: number
  log?: string
  message: string
}

/** Start an already-probed backend, or explain why it did not come up. */
async function startReport(address: BackendAddress, home: string) {
  const result = await startBackend({ agentHome: home, repoRoot, address })
  if ('alreadyRunning' in result) {
    return {
      status: 'running' as const,
      changed: false,
      message: `${address.baseUrl} was already running; nothing to start`,
    }
  }
  if ('skipped' in result) {
    throw new Error(
      `the backend did not start: ${result.reason}${result.tail ? `\n${result.tail}` : ''}${
        result.logPath ? `\nlog: ${result.logPath}` : ''
      }`,
    )
  }
  startedHere = result.child
  return {
    status: 'running' as const,
    changed: true,
    pid: result.pid,
    log: result.logPath,
    message: `started the backend at ${address.baseUrl} (pid ${result.pid})`,
  }
}

/** Stop the recorded backend, or refuse without touching an unrecorded one. */
async function stopReport(address: BackendAddress, home: string) {
  if ((await probeBackend(address.baseUrl)) !== 'ready') {
    clearBackendRecord(home)
    return {
      status: 'stopped' as const,
      changed: false,
      message: `nothing answers on ${address.baseUrl}; already stopped`,
    }
  }
  const result: StopBackendResult = await stopRecordedBackend({
    agentHome: home,
    address,
  })
  if (!result.stopped) {
    throw new Error(
      `refusing to stop ${address.baseUrl}: ${result.reason ?? 'the backend is not owned by this CLI'}. ` +
        'A backend started elsewhere (for example `npm --prefix frontend run dev:all`) must be restarted there.',
    )
  }
  return {
    status: 'stopped' as const,
    changed: true,
    pid: result.pid,
    log: result.logPath,
    message: `stopped the backend at ${address.baseUrl} (pid ${result.pid})`,
  }
}

export interface BackendToolOptions {
  /** Called after the backend is confirmed running, so capabilities can reload. */
  onBackendRunning?: (ctx: ExtensionToolContext) => Promise<void> | void
}

/**
 * Start, stop, or restart the local FastAPI backend.
 *
 * Ownership is strict on purpose: `stop` and `restart` only act on a backend the
 * CLI recorded at spawn, so an unrelated process holding the same port is never
 * killed. The launcher's own auto-start writes that record too.
 */
export function registerBackendTool(
  pi: ExtensionAPI,
  options: BackendToolOptions = {},
): void {
  pi.registerTool(
    defineTool({
      name: BACKEND_TOOL_NAME,
      label: BACKEND_TOOL_NAME,
      description:
        'Start, stop, or restart the local MBForge FastAPI backend. Use it after backend code changes so the running process picks them up, or when capabilities fail because the backend is down. The tool only stops a backend this CLI started.',
      promptGuidelines: [
        'Call `backend_control` only when the user asks for it, or when a capability failed because the backend is not running or is running stale code. Do not restart it during an ingest run or a reviewed task: a restart kills in-flight work.',
        "A refusal that says the backend was not started by this CLI is final; report it with that backend's own start command instead of retrying.",
      ],
      parameters,
      ...toolRenderers(BACKEND_TOOL_NAME, true),
      async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
        const address = backendAddress()
        if (!address.local) {
          throw new Error(
            `backend_control manages only a local backend; ${address.baseUrl} is remote`,
          )
        }
        const home = agentHome()
        const action = params.action as 'start' | 'stop' | 'restart'

        let outcome: Omit<BackendToolReport, 'action' | 'base_url'>
        if (action === 'start') {
          outcome = await startReport(address, home)
        } else if (action === 'stop') {
          outcome = await stopReport(address, home)
        } else {
          await stopReport(address, home)
          outcome = await startReport(address, home)
        }

        if (outcome.status === 'running') {
          await options.onBackendRunning?.(ctx)
        }

        const report: BackendToolReport = {
          action,
          base_url: address.baseUrl,
          ...outcome,
        }
        return {
          content: [{ type: 'text', text: JSON.stringify(report) }],
          details: report,
        }
      },
    }),
  )
}
