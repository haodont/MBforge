/**
 * Shared persistence primitives for the agent's local state files.
 *
 * Every store under the agent home (memory layers, improvement log, review
 * queue, provider config, backend record) replaces files atomically and
 * serializes its writes; these helpers keep that contract in one place.
 */

import {
  existsSync,
  mkdirSync,
  readFileSync,
  renameSync,
  unlinkSync,
  writeFileSync,
} from 'node:fs'
import { mkdir, readFile, rename, unlink, writeFile } from 'node:fs/promises'
import { dirname } from 'node:path'

function temporaryPath(path: string): string {
  return `${path}.${process.pid}.${Date.now()}.${Math.random().toString(16).slice(2)}.tmp`
}

/** Replace a file atomically: write a sibling temporary, then rename over it. */
export async function atomicWrite(
  path: string,
  text: string,
  mode = 0o600,
): Promise<void> {
  await mkdir(dirname(path), { recursive: true, mode: 0o700 })
  const temporary = temporaryPath(path)
  try {
    await writeFile(temporary, text, { encoding: 'utf8', mode })
    await rename(temporary, path)
  } catch (error) {
    try {
      await unlink(temporary)
    } catch {
      // Best effort cleanup; preserve the original write error.
    }
    throw error
  }
}

/** Synchronous variant for callers that are sync end to end. */
export function atomicWriteSync(path: string, text: string, mode?: number): void {
  mkdirSync(dirname(path), { recursive: true, mode: 0o700 })
  const temporary = temporaryPath(path)
  try {
    writeFileSync(temporary, text, { encoding: 'utf8', mode })
    renameSync(temporary, path)
  } catch (error) {
    try {
      unlinkSync(temporary)
    } catch {
      // Best effort cleanup; preserve the original write error.
    }
    throw error
  }
}

function parseJson(raw: string, path: string): unknown {
  try {
    return JSON.parse(raw) as unknown
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error)
    throw new Error(`${path} is not valid JSON: ${reason}`)
  }
}

/**
 * Read a UTF-8 JSON document. A missing or empty file is `undefined`; invalid
 * JSON throws with the path. Shape validation belongs to the caller.
 */
export async function readJsonFile(path: string): Promise<unknown> {
  if (!existsSync(path)) return undefined
  const raw = (await readFile(path, 'utf8')).replace(/^\uFEFF/, '').trim()
  return raw ? parseJson(raw, path) : undefined
}

/** Synchronous variant of {@link readJsonFile}. */
export function readJsonFileSync(path: string): unknown {
  if (!existsSync(path)) return undefined
  const raw = readFileSync(path, 'utf8').replace(/^\uFEFF/, '').trim()
  return raw ? parseJson(raw, path) : undefined
}

/**
 * Serialize async operations on one promise chain. A failed operation does
 * not poison the chain; its caller still sees the rejection.
 */
export function createSerializer(): <T>(operation: () => Promise<T>) => Promise<T> {
  let chain: Promise<unknown> = Promise.resolve()
  return <T>(operation: () => Promise<T>): Promise<T> => {
    const run = chain.then(operation)
    chain = run.then(
      () => undefined,
      () => undefined,
    )
    return run
  }
}