/**
 * MBForge backend process lifecycle, shared by the launcher and the agent tool.
 *
 * `scripts/cli.mjs` starts the backend before pi, but pi and this extension run
 * in a *different* process, so the `ChildProcess` handle cannot cross over. The
 * backend that a CLI started is therefore recorded in
 * `{agent_home}/backend.json` (pid, address, log); `backend_control` stops only
 * a backend with that record, never whatever happens to hold the port.
 */

import { spawn, spawnSync } from 'node:child_process'
import type { ChildProcess } from 'node:child_process'
import {
  closeSync,
  createWriteStream,
  existsSync,
  mkdirSync,
  openSync,
  readSync,
  rmSync,
  statSync,
} from 'node:fs'
import { join } from 'node:path'
import { setTimeout as sleep } from 'node:timers/promises'

import { atomicWriteSync, readJsonFileSync } from './localStore.js'

const PROBE_TIMEOUT_MS = 1_000
const START_TIMEOUT_MS = 45_000
const STOP_TIMEOUT_MS = 10_000
const POLL_INTERVAL_MS = 300
const RECORD_NAME = 'backend.json'

export type BackendState = 'ready' | 'offline' | 'occupied'

export interface BackendAddress {
  baseUrl: string
  host: string
  port: number
  local: boolean
}

/** A backend a CLI started, so a later process may stop it deliberately. */
export interface BackendRecord {
  pid: number
  host: string
  port: number
  baseUrl: string
  logPath: string
  startedAt: string
}

/** Backend address used by the extension and by the auto-start probe. */
export function backendAddress(
  env: NodeJS.ProcessEnv = process.env,
): BackendAddress {
  const explicit = env.MBFORGE_BACKEND_URL
  if (explicit) {
    const url = new URL(explicit)
    return {
      baseUrl: explicit.replace(/\/+$/, ''),
      host: url.hostname,
      port: Number(url.port || (url.protocol === 'https:' ? 443 : 80)),
      local: isLocalHost(url.hostname),
    }
  }

  const host = env.MBFORGE_BACKEND_HOST ?? '127.0.0.1'
  const port = Number(env.MBFORGE_BACKEND_PORT ?? '18792')
  return {
    baseUrl: `http://${host}:${port}`,
    host,
    port,
    local: isLocalHost(host),
  }
}

function isLocalHost(host: string): boolean {
  return ['127.0.0.1', 'localhost', '::1', '[::1]', '0.0.0.0'].includes(
    host.toLowerCase(),
  )
}

/**
 * Classify what answers on the backend address.
 *
 * `ready` is a MBForge API, `occupied` is anything else listening there (an
 * unrelated process, or one still booting), `offline` is nothing at all.
 */
export async function probeBackend(baseUrl: string): Promise<BackendState> {
  let response: Response
  try {
    response = await fetch(new URL('/api/v1/capabilities', baseUrl), {
      signal: AbortSignal.timeout(PROBE_TIMEOUT_MS),
    })
  } catch (error) {
    // A timeout means something is listening but not answering; do not race a
    // second backend onto the same port.
    const name = (error as { name?: string } | undefined)?.name
    return name === 'TimeoutError' || name === 'AbortError'
      ? 'occupied'
      : 'offline'
  }

  if (!response.ok) return 'occupied'
  try {
    const payload = (await response.json()) as {
      success?: unknown
      capabilities?: unknown
    }
    return payload?.success === true && Array.isArray(payload.capabilities)
      ? 'ready'
      : 'occupied'
  } catch {
    return 'occupied'
  }
}

export function backendRecordPath(agentHome: string): string {
  return join(agentHome, RECORD_NAME)
}

export function readBackendRecord(
  agentHome: string,
): BackendRecord | undefined {
  try {
    const parsed = readJsonFileSync(backendRecordPath(agentHome)) as
      Partial<BackendRecord> | undefined
    if (
      !parsed ||
      typeof parsed.pid !== 'number' ||
      !Number.isInteger(parsed.pid) ||
      parsed.pid <= 0
    )
      return undefined
    if (typeof parsed.port !== 'number' || typeof parsed.baseUrl !== 'string')
      return undefined
    return {
      pid: parsed.pid,
      host: typeof parsed.host === 'string' ? parsed.host : '127.0.0.1',
      port: parsed.port,
      baseUrl: parsed.baseUrl,
      logPath: typeof parsed.logPath === 'string' ? parsed.logPath : '',
      startedAt: typeof parsed.startedAt === 'string' ? parsed.startedAt : '',
    }
  } catch {
    return undefined
  }
}

/** Write the record atomically; a half-written file must never look like an owner. */
export function writeBackendRecord(
  agentHome: string,
  record: BackendRecord,
): void {
  atomicWriteSync(
    backendRecordPath(agentHome),
    `${JSON.stringify(record, null, 2)}\n`,
  )
}

export function clearBackendRecord(agentHome: string): void {
  rmSync(backendRecordPath(agentHome), { force: true })
}

function backendCommand(repoRoot: string): {
  command: string
  prefixArgs: string[]
} {
  const venvPython =
    process.platform === 'win32'
      ? join(repoRoot, '.venv', 'Scripts', 'python.exe')
      : join(repoRoot, '.venv', 'bin', 'python')
  if (existsSync(venvPython)) {
    return { command: venvPython, prefixArgs: [] }
  }
  return {
    command: process.platform === 'win32' ? 'uv.exe' : 'uv',
    prefixArgs: ['run', 'python'],
  }
}

function readTail(path: string, maxBytes = 2_000): string {
  try {
    const size = statSync(path).size
    if (size === 0) return ''
    const length = Math.min(maxBytes, size)
    const buffer = Buffer.alloc(length)
    const fd = openSync(path, 'r')
    try {
      readSync(fd, buffer, 0, length, size - length)
    } finally {
      closeSync(fd)
    }
    return buffer.toString('utf8').trim()
  } catch {
    return ''
  }
}

function numberInRange(value: number, min: number, max: number): boolean {
  return Number.isInteger(value) && value >= min && value <= max
}

export interface StartBackendOptions {
  agentHome: string
  repoRoot: string
  address: BackendAddress
  onChild?: (child: ChildProcess) => void
}

export type StartBackendResult =
  | { alreadyRunning: true }
  | { skipped: true; reason: string; logPath?: string; tail?: string }
  | {
      started: true
      child: ChildProcess
      logPath: string
      host: string
      port: number
      pid: number
    }

/**
 * Start the MBForge backend when nothing is listening. A backend that is
 * already running is never touched or stopped by the caller.
 */
export async function startBackend(
  options: StartBackendOptions,
): Promise<StartBackendResult> {
  const { agentHome, repoRoot, address, onChild } = options
  if (!address.local) {
    return { skipped: true, reason: 'backend address is not local' }
  }
  if (!numberInRange(address.port, 1, 65535)) {
    return { skipped: true, reason: `invalid backend port ${address.port}` }
  }
  if (!existsSync(join(repoRoot, 'pyproject.toml'))) {
    return { skipped: true, reason: 'not a source checkout' }
  }

  const before = await probeBackend(address.baseUrl)
  if (before === 'ready') return { alreadyRunning: true }
  if (before === 'occupied') {
    return {
      skipped: true,
      reason: `port ${address.port} is in use but /api/v1/capabilities is not ready`,
    }
  }

  const logDir = join(agentHome, 'logs')
  mkdirSync(logDir, { recursive: true })
  const logPath = join(logDir, 'backend.log')
  const log = createWriteStream(logPath, { flags: 'a' })
  log.on('error', () => {
    // Logging must never take the launcher down.
  })

  const { command, prefixArgs } = backendCommand(repoRoot)
  const child = spawn(
    command,
    // Match `dev:all`: reload on Python source changes so a launcher-started
    // backend never keeps serving stale code after an edit.
    [
      ...prefixArgs,
      '-m',
      'mbforge',
      '--host',
      address.host,
      '--port',
      String(address.port),
      '--no-browser',
      '--reload',
    ],
    {
      cwd: repoRoot,
      env: {
        ...process.env,
        MBFORGE_HOST: address.host,
        MBFORGE_PORT: String(address.port),
        MBFORGE_BACKEND_HOST: address.host,
        MBFORGE_BACKEND_PORT: String(address.port),
        MBFORGE_NO_BROWSER: '1',
      },
      detached: process.platform !== 'win32',
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    },
  )

  child.stdout?.pipe(log)
  child.stderr?.pipe(log)
  onChild?.(child)

  let spawnError: Error | undefined
  child.once('error', (error) => {
    spawnError = error
  })

  const deadline = Date.now() + START_TIMEOUT_MS
  let state = await probeBackend(address.baseUrl)
  while (state !== 'ready' && Date.now() < deadline) {
    if (spawnError) break
    if (child.exitCode !== null) {
      // Another launcher may be starting the same backend; give it a moment.
      await sleep(500)
      state = await probeBackend(address.baseUrl)
      break
    }
    await sleep(POLL_INTERVAL_MS)
    state = await probeBackend(address.baseUrl)
  }

  // The child must still be alive: if it exited on its own (a bind conflict it
  // reported in the log), the API that answered belongs to someone else and
  // recording its pid would hand `stop` a process this CLI never spawned.
  if (state === 'ready' && child.pid && child.exitCode === null) {
    writeBackendRecord(agentHome, {
      pid: child.pid,
      host: address.host,
      port: address.port,
      baseUrl: address.baseUrl,
      logPath,
      startedAt: new Date().toISOString(),
    })
    return {
      started: true,
      child,
      logPath,
      host: address.host,
      port: address.port,
      pid: child.pid,
    }
  }

  stopBackend(child)
  log.end()
  return {
    skipped: true,
    reason:
      spawnError?.message ??
      `backend did not become ready on ${address.baseUrl}`,
    logPath,
    tail: readTail(logPath),
  }
}

/** Kill a process and its children. */
export function killTree(pid: number): void {
  if (process.platform === 'win32') {
    spawnSync('taskkill', ['/pid', String(pid), '/T', '/F'], {
      stdio: 'ignore',
      windowsHide: true,
    })
    return
  }
  try {
    process.kill(-pid, 'SIGTERM')
  } catch {
    try {
      process.kill(pid, 'SIGTERM')
    } catch {
      // Process already gone.
    }
  }
}

/** Stop only a backend this process started, including its child tree. */
export function stopBackend(child: ChildProcess | null | undefined): void {
  if (!child || child.exitCode !== null || !child.pid) return
  killTree(child.pid)
}

export interface StopBackendResult {
  stopped: boolean
  pid?: number
  logPath?: string
  reason?: string
}

/**
 * Stop the backend recorded as started by a CLI. A backend that no record
 * accounts for is left running: it may be a dev server or an unrelated process
 * that merely holds the port.
 */
export async function stopRecordedBackend(options: {
  agentHome: string
  address: BackendAddress
  timeoutMs?: number
}): Promise<StopBackendResult> {
  const { agentHome, address, timeoutMs = STOP_TIMEOUT_MS } = options
  const record = readBackendRecord(agentHome)
  if (!record) {
    return {
      stopped: false,
      reason: `no CLI-started backend is recorded at ${backendRecordPath(agentHome)}`,
    }
  }
  if (record.baseUrl !== address.baseUrl) {
    clearBackendRecord(agentHome)
    return {
      stopped: false,
      reason: `the recorded backend was ${record.baseUrl}, not ${address.baseUrl}; record discarded`,
    }
  }

  const before = await probeBackend(address.baseUrl)
  if (before !== 'ready') {
    clearBackendRecord(agentHome)
    return {
      stopped: false,
      reason: 'backend was not running; stale record discarded',
    }
  }

  killTree(record.pid)
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if ((await probeBackend(address.baseUrl)) !== 'ready') {
      clearBackendRecord(agentHome)
      return { stopped: true, pid: record.pid, logPath: record.logPath }
    }
    await sleep(POLL_INTERVAL_MS)
  }
  return {
    stopped: false,
    pid: record.pid,
    logPath: record.logPath,
    reason: `pid ${record.pid} still answers on ${address.baseUrl}`,
  }
}
