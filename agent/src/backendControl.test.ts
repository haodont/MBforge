// @tested-functions probeBackend stopRecordedBackend writeBackendRecord
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { mkdtemp, rm } from 'node:fs/promises'
import { createServer } from 'node:http'
import type { AddressInfo } from 'node:net'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'

import {
  backendRecordPath,
  probeBackend,
  readBackendRecord,
  stopRecordedBackend,
  writeBackendRecord,
  type BackendRecord,
} from './backendControl.js'

const CAPABILITIES = JSON.stringify({ success: true, capabilities: [] })

function listen(server: ReturnType<typeof createServer>): Promise<number> {
  const { promise, resolve } = Promise.withResolvers<number>()
  server.listen(0, '127.0.0.1', () => resolve((server.address() as AddressInfo).port))
  return promise
}

function close(server: ReturnType<typeof createServer>): Promise<void> {
  const { promise, resolve } = Promise.withResolvers<void>()
  server.close(() => resolve())
  return promise
}

/** Serve the readiness probe with a fake MBForge capabilities payload. */
async function serve(): Promise<{ url: string; port: number; shutdown: () => Promise<void> }> {
  const server = createServer((_request, response) => {
    response.setHeader('content-type', 'application/json')
    response.end(CAPABILITIES)
  })
  const port = await listen(server)
  return { url: `http://127.0.0.1:${port}`, port, shutdown: () => close(server) }
}

test('the probe separates a MBForge API from an unrelated listener and from nothing', async () => {
  const ready = await serve()
  const wrong = createServer((_request, response) => {
    response.statusCode = 500
    response.end('not mbforge')
  })
  const wrongPort = await listen(wrong)
  const released = createServer()
  const closedPort = await listen(released)
  await close(released)
  try {
    assert.equal(await probeBackend(ready.url), 'ready')
    assert.equal(await probeBackend(`http://127.0.0.1:${wrongPort}`), 'occupied')
    assert.equal(await probeBackend(`http://127.0.0.1:${closedPort}`), 'offline')
  } finally {
    await ready.shutdown()
    await close(wrong)
  }
})

test('stop leaves a backend that no CLI started answering', async () => {
  const home = await mkdtemp(join(tmpdir(), 'mbforge-backend-'))
  const backend = await serve()
  try {
    const result = await stopRecordedBackend({
      agentHome: home,
      address: { baseUrl: backend.url, host: '127.0.0.1', port: backend.port, local: true },
      timeoutMs: 500,
    })
    assert.equal(result.stopped, false)
    assert.match(result.reason ?? '', /no CLI-started backend/)
    assert.equal(await probeBackend(backend.url), 'ready', 'the unrelated server is untouched')
  } finally {
    await backend.shutdown()
    await rm(home, { recursive: true, force: true })
  }
})

test('stop kills the recorded backend and clears the record', async () => {
  const home = await mkdtemp(join(tmpdir(), 'mbforge-backend-'))
  const occupied = createServer()
  const port = await listen(occupied)
  await close(occupied)

  // The recorded process is the server itself, so the post-kill probe proves
  // the kill took the API down rather than stopping some bystander.
  const child = spawn(
    process.execPath,
    [
      '-e',
      `const server = require('node:http').createServer((q, s) => {` +
        `s.setHeader('content-type', 'application/json'); s.end(${JSON.stringify(CAPABILITIES)}) });` +
        `server.listen(${port}, '127.0.0.1', () => process.stdout.write('ready\\n'))`,
    ],
    { stdio: ['ignore', 'pipe', 'ignore'], detached: process.platform !== 'win32', windowsHide: true },
  )
  const listening = Promise.withResolvers<void>()
  child.stdout?.once('data', () => listening.resolve())
  const address = { baseUrl: `http://127.0.0.1:${port}`, host: '127.0.0.1', port, local: true }
  try {
    await listening.promise
    assert.equal(await probeBackend(address.baseUrl), 'ready')
    const record: BackendRecord = {
      pid: child.pid as number,
      host: '127.0.0.1',
      port,
      baseUrl: address.baseUrl,
      logPath: join(home, 'logs', 'backend.log'),
      startedAt: new Date().toISOString(),
    }
    writeBackendRecord(home, record)
    assert.equal(readBackendRecord(home)?.pid, child.pid)

    const result = await stopRecordedBackend({ agentHome: home, address, timeoutMs: 10_000 })
    assert.equal(result.stopped, true, result.reason)
    assert.equal(await probeBackend(address.baseUrl), 'offline')
    assert.equal(readBackendRecord(home), undefined)
    assert.equal(existsSync(backendRecordPath(home)), false)
  } finally {
    child.kill('SIGKILL')
    await rm(home, { recursive: true, force: true })
  }
})
