import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { basename, dirname, join } from 'node:path'

const CHILD_OUTPUT_LIMIT = 200_000

/** Resolve the repository root when the agent runs from its `agent/` subdir. */
export function projectCwd(cwd: string): string {
  const parent = dirname(cwd)
  if (
    basename(cwd).toLowerCase() === 'agent' &&
    (existsSync(join(parent, 'pyproject.toml')) || existsSync(join(parent, '.git')))
  ) {
    return parent
  }
  return cwd
}

/** Re-invoke the running pi entry, falling back to a `pi` on PATH. */
export function piInvocation(args: string[]): { command: string; args: string[] } {
  const script = process.argv[1]
  if (script && existsSync(script)) {
    return { command: process.execPath, args: [script, ...args] }
  }
  return { command: 'pi', args }
}

export interface PiTextInput {
  cwd: string
  args: string[]
  env?: Record<string, string>
  /** Absolute deadline. Omit for background work that must run to completion. */
  timeoutMs?: number
  /** Kill only after this long with no stdout/stderr activity. */
  idleTimeoutMs?: number
  signal?: AbortSignal
  label: string
  /** Prompt delivered on stdin, avoiding the Windows command-line length limit. */
  stdin?: string
}

/** Run a one-shot pi child with bounded output and optional deadlines. */
export async function spawnPiText(input: PiTextInput): Promise<string> {
  const invocation = piInvocation(input.args)
  const { promise, resolve, reject } = Promise.withResolvers<string>()
  const child = spawn(invocation.command, invocation.args, {
    cwd: input.cwd,
    shell: false,
    windowsHide: true,
    stdio: ['pipe', 'pipe', 'pipe'],
    env: { ...process.env, ...input.env },
  })
  // A large prompt lives on stdin; closing it would otherwise surface as an
  // unhandled EPIPE when the child exits early.
  child.stdin?.on('error', () => {})
  child.stdin?.end(input.stdin ?? '')
  let stdout = ''
  let stderr = ''
  let settled = false
  let hardTimer: NodeJS.Timeout | undefined
  let idleTimer: NodeJS.Timeout | undefined
  const finish = (error: Error | undefined, output = '') => {
    if (settled) return
    settled = true
    clearTimeout(hardTimer)
    clearTimeout(idleTimer)
    input.signal?.removeEventListener('abort', abort)
    if (error) reject(error)
    else resolve(output)
  }
  const abort = () => {
    child.kill()
    finish(new Error(`${input.label} was aborted`))
  }
  const armIdle = () => {
    if (!input.idleTimeoutMs || input.idleTimeoutMs <= 0) return
    clearTimeout(idleTimer)
    idleTimer = setTimeout(() => {
      child.kill()
      finish(
        new Error(
          `${input.label} stalled after ${input.idleTimeoutMs}ms without output`,
        ),
      )
    }, input.idleTimeoutMs)
  }
  if (input.timeoutMs && input.timeoutMs > 0) {
    hardTimer = setTimeout(() => {
      child.kill()
      finish(new Error(`${input.label} timed out after ${input.timeoutMs}ms`))
    }, input.timeoutMs)
  }
  armIdle()
  child.stdout.setEncoding('utf8')
  child.stderr.setEncoding('utf8')
  child.stdout.on('data', (chunk: string) => {
    stdout = (stdout + chunk).slice(-CHILD_OUTPUT_LIMIT)
    armIdle()
  })
  child.stderr.on('data', (chunk: string) => {
    stderr = (stderr + chunk).slice(-CHILD_OUTPUT_LIMIT)
    armIdle()
  })
  child.on('error', (error) => finish(error, ''))
  child.on('close', (code) => {
    if (code === 0 && stdout.trim()) {
      finish(undefined, stdout.trim())
      return
    }
    finish(
      new Error(
        `${input.label} failed (exit ${code ?? 'unknown'}): ${stderr.trim() || stdout.trim() || 'no output'}`,
      ),
      '',
    )
  })
  if (input.signal) {
    if (input.signal.aborted) abort()
    else input.signal.addEventListener('abort', abort, { once: true })
  }
  return promise
}