import assert from 'node:assert/strict'
import test from 'node:test'

import { loadCapabilityToolset } from './capabilities.js'

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
