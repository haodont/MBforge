/**
 * Session modes are the single switch for agent depth:
 *
 * - `auto`: read and mutating MBForge capabilities, no repository tools.
 * - `dev`: all capabilities plus built-in repository/code tools.
 *
 * There is no read-only session mode. A session that must not mutate library
 * data is created by withholding the capability token: the backend derives the
 * invocation mode from that token and answers every mutating call with 403.
 */
export type SessionMode = 'auto' | 'dev'

export function parseSessionMode(value: string): SessionMode | undefined {
  const normalized = value.trim().toLowerCase()
  if (normalized === 'auto' || normalized === 'edit') return 'auto'
  if (normalized === 'dev') return 'dev'
  return undefined
}

/** Resolve the startup mode; `auto` is the default. */
export function resolveSessionMode(
  env: NodeJS.ProcessEnv = process.env,
): SessionMode {
  const mode = parseSessionMode(env.MBFORGE_AGENT_MODE ?? '')
  if (mode !== undefined) return mode

  const legacyDev = ['1', 'true', 'yes'].includes(
    (env.MBFORGE_AGENT_DEV ?? '').toLowerCase(),
  )
  return legacyDev ? 'dev' : 'auto'
}

/** Whether built-in repository/code tools belong to this session mode. */
export function usesBuiltinTools(mode: SessionMode): boolean {
  return mode === 'dev'
}
