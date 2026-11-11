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

test('capability failures preserve validation details', async (t) => {
  const original = globalThis.fetch
  t.after(() => {
    globalThis.fetch = original
  })
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    if (String(input).endsWith('/api/v1/capabilities')) {
      return new Response(JSON.stringify(manifest), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      })
    }
    return new Response(
      JSON.stringify({
        success: false,
        error: 'invalid capability input',
        error_code: 'validation_error',
        detail: 'bad payload',
        context: {
          validation_errors: [
            { loc: ['limit'], msg: 'Input should be <= 200' },
          ],
        },
      }),
      { status: 422, headers: { 'content-type': 'application/json' } },
    )
  }) as typeof fetch

  const { tools } = await loadCapabilityToolset()
  const tool = tools[0]
  assert.ok(tool)

  await assert.rejects(
    () =>
      tool.execute(
        'call',
        { query: 'x' },
        new AbortController().signal,
        undefined,
        {} as never,
      ),
    /validation_error: invalid capability input; bad payload; limit: Input should be <= 200/,
  )
})
