/**
 * Frontend logger — single logging facade with a production-friendly default.
 *
 * Policy (per operations docs):
 * - `error` always reaches the console and the diagnostics reporter: fatal /
 *   unexpected failures must stay visible in production.
 * - `warn` / `info` / `debug` are development-only; they are suppressed in
 *   production builds so noise from retries, probes and non-blocking
 *   background polls never pollutes the user console.
 *
 * Import from `@/utils/logger`; do not call `console.*` directly.
 */

type LoggerLevel = 'debug' | 'info' | 'warn' | 'error'

const IS_DEV = typeof import.meta !== 'undefined' ? import.meta.env.DEV : false

function output(level: LoggerLevel, args: unknown[]): void {
  switch (level) {
    case 'debug':
      if (IS_DEV) console.debug(...args)
      break
    case 'info':
      if (IS_DEV) console.log(...args)
      break
    case 'warn':
      if (IS_DEV) console.warn(...args)
      break
    case 'error':
      console.error(...args)
      break
  }
}

export const logger = {
  debug(...args: unknown[]): void {
    output('debug', args)
  },
  info(...args: unknown[]): void {
    output('info', args)
  },
  warn(...args: unknown[]): void {
    output('warn', args)
  },
  error(...args: unknown[]): void {
    output('error', args)
  },
}
