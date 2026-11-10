import assert from 'node:assert/strict'
import test from 'node:test'

import { loadCapabilityTools } from './capabilities.js'

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

test('readonly mode registers only non-mutating capabilities', async (t) => {
  stubFetch(t)

  const tools = await loadCapabilityTools('readonly')

  assert.deepEqual(
    tools.map((tool) => tool.name),
    ['search_library'],
  )
})

test('edit mode registers every capability', async (t) => {
  stubFetch(t)

  const tools = await loadCapabilityTools('edit')

  assert.deepEqual(
    tools.map((tool) => tool.name),
    ['search_library', 'update_record'],
  )
})
