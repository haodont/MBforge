import { spawn, spawnSync } from 'node:child_process'
import {
  closeSync,
  createWriteStream,
  existsSync,
  mkdirSync,
  openSync,
  readSync,
  statSync,
} from 'node:fs'
import { join } from 'node:path'
import { setTimeout as sleep } from 'node:timers/promises'

const PROBE_TIMEOUT_MS = 1_000
const START_TIMEOUT_MS = 45_000
const POLL_INTERVAL_MS = 300

/** Backend address used by the extension and by the auto-start probe. */
export function backendAddress() {
  const explicit = process.env.MBFORGE_BACKEND_URL
  if (explicit) {
    const url = new URL(explicit)
    return {
      baseUrl: explicit,
      host: url.hostname,
      port: Number(url.port || (url.protocol === 'https:' ? 443 : 80)),
      local: isLocalHost(url.hostname),
    }
  }

  const host = process.env.MBFORGE_BACKEND_HOST ?? '127.0.0.1'
  const port = Number(process.env.MBFORGE_BACKEND_PORT ?? '18792')
  return {
    baseUrl: `http://${host}:${port}`,
    host,
    port,
    local: isLocalHost(host),
  }
}

function isLocalHost(host) {
  return ['127.0.0.1', 'localhost', '::1', '[::1]', '0.0.0.0'].includes(
    host.toLowerCase(),
  )
}

async function probeCapabilities(baseUrl) {
  let response
  try {
    response = await fetch(new URL('/api/v1/capabilities', baseUrl), {
      signal: AbortSignal.timeout(PROBE_TIMEOUT_MS),
    })
  } catch (error) {
    // A timeout means something is listening but not answering; do not race a
    // second backend onto the same port.
    return error?.name === 'TimeoutError' || error?.name === 'AbortError'
      ? 'occupied'
      : 'offline'
  }

  if (!response.ok) return 'occupied'
  try {
    const payload = await response.json()
    return payload?.success === true && Array.isArray(payload.capabilities)
      ? 'ready'
      : 'occupied'
  } catch {
    return 'occupied'
  }
}

function backendCommand(repoRoot) {
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

function readTail(path, maxBytes = 2_000) {
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

/**
 * Start the MBForge backend when nothing is listening. A backend that is
 * already running is never touched or stopped by the caller.
 */
export async function startBackend({ agentHome, repoRoot, address, onChild }) {
  if (!address.local) {
    return { skipped: true, reason: 'backend address is not local' }
  }
  if (!numberInRange(address.port, 1, 65535)) {
    return { skipped: true, reason: `invalid backend port ${address.port}` }
  }
  if (!existsSync(join(repoRoot, 'pyproject.toml'))) {
    return { skipped: true, reason: 'not a source checkout' }
  }

  const before = await probeCapabilities(address.baseUrl)
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
    [
      ...prefixArgs,
      '-m',
      'mbforge',
      '--host',
      address.host,
      '--port',
      String(address.port),
      '--no-browser',
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

  child.stdout.pipe(log)
  child.stderr.pipe(log)
  onChild?.(child)

  let spawnError
  child.once('error', (error) => {
    spawnError = error
  })

  const deadline = Date.now() + START_TIMEOUT_MS
  let state = await probeCapabilities(address.baseUrl)
  while (state !== 'ready' && Date.now() < deadline) {
    if (spawnError) break
    if (child.exitCode !== null) {
      // Another launcher may be starting the same backend; give it a moment.
      await sleep(500)
      state = await probeCapabilities(address.baseUrl)
      break
    }
    await sleep(POLL_INTERVAL_MS)
    state = await probeCapabilities(address.baseUrl)
  }

  if (state === 'ready') {
    return { started: true, child, logPath, host: address.host, port: address.port }
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

function numberInRange(value, min, max) {
  return Number.isInteger(value) && value >= min && value <= max
}

/** Stop only a backend this process started, including its child tree. */
export function stopBackend(child) {
  if (!child || child.exitCode !== null || !child.pid) return
  if (process.platform === 'win32') {
    spawnSync(
      'taskkill',
      ['/pid', String(child.pid), '/T', '/F'],
      { stdio: 'ignore', windowsHide: true },
    )
    return
  }
  try {
    process.kill(-child.pid, 'SIGTERM')
  } catch {
    try {
      child.kill('SIGTERM')
    } catch {
      // Process already gone.
    }
  }
}
