import assert from 'node:assert/strict'
import test from 'node:test'

import {
  createCapabilityToolsetManager,
  loadCapabilityToolset,
  type CapabilityTool,
  type CapabilityToolset,
} from './capabilities.js'

const manifest = {
  success: true,
  token_path: './unused-token',
  capabilities: [
    {
      name: 'search_library',
      description: 'Search the local library (read-only).',
      mutating: false,
      input_schema: {
        type: 'object',
        properties: { query: { type: 'string' } },
      },
    },
    {
      name: 'update_record',
      description: 'Update a library record.',
      mutating: true,
      input_schema: {
        type: 'object',
        properties: { id: { type: 'string' } },
      },
    },
  ],
}

function stubFetch(t: test.TestContext): void {
  const original = globalThis.fetch
  t.after(() => {
    globalThis.fetch = original
  })
  globalThis.fetch = (async () =>
    new Response(JSON.stringify(manifest), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    })) as typeof fetch
}

test('manifest loads every capability and records mutating names', async (t) => {
  stubFetch(t)

  const { tools, mutatingNames } = await loadCapabilityToolset()

  assert.deepEqual(
    tools.map((tool) => tool.name),
    ['search_library', 'update_record'],
  )
  assert.deepEqual(mutatingNames, ['update_record'])
})

test('capability failures preserve details and add a recovery hint', async (t) => {
  const original = globalThis.fetch
  t.after(() => {
    globalThis.fetch = original
  })
  const stub = (status: number, body: unknown): void => {
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      if (String(input).endsWith('/api/v1/capabilities')) {
        return new Response(JSON.stringify(manifest), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        })
      }
      return new Response(JSON.stringify(body), {
        status,
        headers: { 'content-type': 'application/json' },
      })
    }) as typeof fetch
  }

  stub(422, {
    success: false,
    error: 'invalid capability input',
    error_code: 'validation_error',
    detail: 'bad payload',
    context: {
      validation_errors: [{ loc: ['limit'], msg: 'Input should be <= 200' }],
    },
  })
  const { tools } = await loadCapabilityToolset()
  const tool = tools[0]
  assert.ok(tool)
  const invoke = () =>
    tool.execute(
      'call',
      { query: 'x' },
      new AbortController().signal,
      undefined,
      {} as never,
    )

  await assert.rejects(
    invoke,
    /validation_error: invalid capability input; bad payload; limit: Input should be <= 200; next: fix the listed field errors and retry once/,
  )

  stub(403, {
    success: false,
    error: 'mutating capability requires the capability token',
    error_code: 'capability_forbidden',
  })
  await assert.rejects(
    invoke,
    /capability_forbidden: mutating capability requires the capability token; next: this write is gated by the capability token/,
  )
})

test('capability toolset recovers after an offline start and keeps tools when a refresh fails', async () => {
  const registered: string[] = []
  let available = false
  let version = 1
  const loader = async (): Promise<CapabilityToolset> => {
    if (!available) throw new Error('backend unreachable')
    return {
      tools: [{ name: `cap_v${version}` } as unknown as CapabilityTool],
      mutatingNames: [],
    }
  }
  const manager = createCapabilityToolsetManager(
    (tool) => registered.push(tool.name),
    undefined,
    loader,
  )

  await manager.load()
  assert.deepEqual(
    manager.tools,
    [],
    'an offline start registers no capability',
  )
  assert.match(manager.loadError ?? '', /backend unreachable/)

  available = true
  const recovered = await manager.reload()
  assert.equal(recovered.ok, true)
  assert.equal(
    manager.loadError,
    undefined,
    'a successful reload clears the offline state',
  )
  assert.deepEqual(registered, ['cap_v1'])
  assert.deepEqual(
    manager.tools.map((tool: CapabilityTool) => tool.name),
    ['cap_v1'],
  )

  version = 2
  const refreshed = await manager.reload()
  assert.equal(refreshed.ok, true)
  assert.deepEqual(
    registered,
    ['cap_v1', 'cap_v2'],
    'reload re-registers under the same names',
  )
  assert.deepEqual(
    manager.tools.map((tool: CapabilityTool) => tool.name),
    ['cap_v2'],
    'the active list follows the new manifest',
  )

  available = false
  const failed = await manager.reload()
  assert.equal(failed.ok, false)
  assert.deepEqual(
    manager.tools.map((tool: CapabilityTool) => tool.name),
    ['cap_v2'],
    'a failed refresh keeps the previous toolset',
  )
  assert.equal(
    manager.loadError,
    undefined,
    'a working session does not flip offline on a failed refresh',
  )
})
