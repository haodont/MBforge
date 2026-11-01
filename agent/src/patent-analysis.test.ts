/**
 * Offline boundary tests for the Patent-analysis runtime.
 * Functions: parsePatentRequest, createBudgetGuard, createPatentTools,
 * registerAttempt/cancelAttempt/activeAttemptIds, handlePatentAnalysis.
 *
 * They protect what the Python side depends on and never touch a provider, the
 * external network or a real backend: the request gate, the budget arithmetic (unknown usage
 * stays unknown), the cancel registry, and the fact that the task credential is
 * captured by the tools rather than exposed as a parameter the model can set.
 */

import assert from 'node:assert/strict'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createServer } from 'node:http'
import type { AddressInfo } from 'node:net'
import { test } from 'node:test'

import {
  PATENT_PROTOCOL_VERSION,
  PATENT_TOOL_NAMES,
  activeAttemptIds,
  cancelAttempt,
  createBudgetGuard,
  createPatentTools,
  handlePatentAnalysis,
  parsePatentRequest,
  registerAttempt,
  unregisterAttempt,
  type PatentBudget,
} from './patent-analysis.js'
import { readBody } from './http.js'

const BUDGET: PatentBudget = {
  max_model_turns: 2,
  wall_clock_seconds: 60,
  max_total_tokens: 1000,
  digest_char_budget: 1000,
  request_timeout_seconds: 30,
}

function runRequest(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    protocol_version: PATENT_PROTOCOL_VERSION,
    doc_id: 'doc-1',
    run_id: 'run-1',
    attempt_id: 'attempt-1',
    evidence_signature: 'sig-1',
    credential: 'credential-123',
    budget: BUDGET,
    gaps: [
      {
        gap_id: 'complex_activity_table:ev-21',
        gap_kind: 'table',
        code: 'complex_activity_table',
        page_start: 21,
        page_end: 21,
        evidence_ids: ['ev-21'],
        excerpt: '| 化合物编号 | IC50(nM) |',
      },
    ],
    ...overrides,
  }
}

test('the request gate validates a run and clamps its budget, which the guard then enforces', () => {
  assert.equal(parsePatentRequest(runRequest({ protocol_version: '1' })).ok, false)
  assert.equal(parsePatentRequest(runRequest({ doc_id: '' })).ok, false)
  assert.equal(parsePatentRequest(runRequest({ attempt_id: '' })).ok, false)
  assert.equal(parsePatentRequest(runRequest({ evidence_signature: '' })).ok, false)
  assert.equal(parsePatentRequest(runRequest({ credential: 'short' })).ok, false)

  const parsed = parsePatentRequest(runRequest({ gaps: undefined }))
  assert.equal(parsed.ok, true)
  if (!parsed.ok) return
  assert.deepEqual(parsed.value.gaps, [])

  // A gap without an identity is not work: it is dropped, not answered blindly.
  const partial = parsePatentRequest(
    runRequest({ gaps: [{ gap_kind: 'table' }, { gap_id: 'g-1', gap_kind: 'table' }] }),
  )
  assert.equal(partial.ok, true)
  if (!partial.ok) return
  assert.deepEqual(
    partial.value.gaps.map((gap) => gap.gap_id),
    ['g-1'],
  )

  // Budget overrides are clamped, not trusted.
  const clamped = parsePatentRequest(
    runRequest({
      budget: { ...BUDGET, max_model_turns: 10_000, wall_clock_seconds: -5 },
    }),
  )
  assert.equal(clamped.ok, true)
  if (!clamped.ok) return
  assert.equal(clamped.value.budget.max_model_turns, 200)
  assert.equal(clamped.value.budget.wall_clock_seconds, 5)
  assert.equal(clamped.value.budget.max_total_tokens, BUDGET.max_total_tokens)

  // A missing budget falls back to the documented engineering defaults.
  const fallback = parsePatentRequest(runRequest({ budget: undefined }))
  assert.equal(fallback.ok, true)
  if (!fallback.ok) return
  assert.equal(fallback.value.budget.max_model_turns, 24)

  // The guard enforces the clamped budget: turns, tokens and the wall clock.
  let now = 0
  const turns = createBudgetGuard(BUDGET, () => now)
  turns.noteTurn()
  turns.noteTurn()
  assert.equal(turns.exceeded(), null)
  turns.noteTurn()
  assert.match(String(turns.exceeded()), /turn budget/)

  const tokens = createBudgetGuard(BUDGET, () => 0)
  tokens.noteUsage({ input: 600, output: 500 })
  assert.equal(tokens.stats().tokens, 1100)
  assert.match(String(tokens.exceeded()), /token budget/)

  const clock = createBudgetGuard(BUDGET, () => now)
  now = 61_000
  assert.match(String(clock.exceeded()), /wall clock/)

  // Unknown provider usage stays unknown instead of counting as zero.
  const unknown = createBudgetGuard(BUDGET, () => 0)
  assert.equal(unknown.noteUsage(undefined), null)
  assert.equal(unknown.stats().tokens, null)
  assert.equal(unknown.exceeded(), null)
  unknown.noteUsage({ totalTokens: 400 })
  assert.equal(unknown.stats().tokens, 400)

  // Tool calls are accounted separately from model turns (re-reading a gap is
  // not progress, so an open gap must not advance on tool calls alone).
  const gaps = createBudgetGuard({ ...BUDGET, max_model_turns: 20 }, () => 0)
  for (let turn = 0; turn < 4; turn += 1) {
    gaps.noteTurn()
    gaps.noteToolCall()
  }
  assert.equal(gaps.exceeded(), null)
  assert.equal(gaps.stats().turns, 4)
  assert.equal(gaps.stats().tool_calls, 4)
})

test('the runtime registers one in-flight attempt, never exposes the credential, and hands out one gap at a time', async () => {
  let aborted = 0
  registerAttempt('attempt-offline', async () => {
    aborted += 1
  })
  assert.deepEqual(activeAttemptIds(), ['attempt-offline'])

  assert.equal(cancelAttempt('attempt-offline'), true)
  assert.equal(cancelAttempt('attempt-unknown'), false)
  assert.equal(aborted, 1)

  unregisterAttempt('attempt-offline')
  assert.equal(cancelAttempt('attempt-offline'), false)
  assert.deepEqual(activeAttemptIds(), [])

  // The loop a live run actually hit: 24 tool calls, every one get_gap, and no
  // submission until the budget ran out. The backend here is a local fixture.
  let gapCalls = 0
  let submitCalls = 0
  const server = createServer((request, response) => {
    const chunks: Buffer[] = []
    request.on('data', (chunk: Buffer) => chunks.push(chunk))
    request.on('end', () => {
      const body = JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}') as {
        gap_id?: string
        answer?: unknown
      }
      response.writeHead(200, { 'content-type': 'application/json' })
      if (body.answer) {
        submitCalls += 1
        response.end(JSON.stringify({ success: true }))
        return
      }
      gapCalls += 1
      const gapId = body.gap_id || (gapCalls === 1 ? 'gap-1' : 'gap-2')
      response.end(
        JSON.stringify({
          success: true,
          gap: {
            gap_id: gapId,
            gap_kind: 'table',
            code: 'complex_activity_table',
            excerpt: '| 化合物编号 | IC50(nM) |',
          },
        }),
      )
    })
  })
  const baseUrl = await new Promise<string>((resolve) => {
    server.listen(0, '127.0.0.1', () => {
      const address = server.address() as AddressInfo
      resolve(`http://127.0.0.1:${address.port}`)
    })
  })

  const previous = process.env.MBFORGE_BACKEND_URL
  process.env.MBFORGE_BACKEND_URL = baseUrl
  try {
    const tools = createPatentTools('credential-123', { onSubmit: () => {} })
    assert.deepEqual(
      tools.map((tool) => tool.name),
      [...PATENT_TOOL_NAMES],
    )
    for (const tool of tools) {
      assert.ok(
        !JSON.stringify(tool.parameters ?? {}).includes('credential'),
        `${tool.name} must not expose a credential parameter`,
      )
    }
    // The runtime dispatches every tool through one untyped call signature, which
    // the SDK's per-tool generics cannot express: narrow the array once, here.
    type CallableTool = {
      name: string
      execute: (
        id: string,
        params: Record<string, unknown>,
      ) => Promise<{ content: Array<{ text?: string }> }>
    }
    const callableTools = tools as unknown as CallableTool[]
    const gapTool = callableTools.find((tool) => tool.name === 'get_gap')
    const submitTool = callableTools.find((tool) => tool.name === 'submit_gap_answer')
    assert.ok(gapTool && submitTool)

    // The tools are called the way the runtime calls them; only the text matters here.
    const callText = async (tool: CallableTool, params: Record<string, unknown>) => {
      const result = await tool.execute('call', params)
      return result.content.map((part) => part.text ?? '').join('\n')
    }

    const first = await callText(gapTool, { gap_id: '' })
    assert.equal(gapCalls, 1)
    assert.match(first, /submit it with submit_gap_answer/)

    const second = await callText(gapTool, { gap_id: '' })
    assert.equal(gapCalls, 1, 'a new gap must not be fetched while one is open')
    assert.match(second, /still unanswered/)

    const reread = await callText(gapTool, { gap_id: 'gap-1' })
    assert.equal(gapCalls, 2, 'the gap in hand may still be re-read')
    assert.match(reread, /gap-1/)

    await callText(submitTool, {
      answer: {
        gap_id: 'gap-1',
        status: 'unanswerable',
        unanswerable_reason: 'no_attribution',
      },
    })
    assert.equal(submitCalls, 1)

    const third = await callText(gapTool, { gap_id: '' })
    assert.equal(gapCalls, 3, 'an accepted answer releases the next gap')
    assert.match(third, /gap-2/)
  } finally {
    if (previous === undefined) delete process.env.MBFORGE_BACKEND_URL
    else process.env.MBFORGE_BACKEND_URL = previous
    server.close()
  }
})

test('a stalled gap expires and the next session repairs a rejected answer with host-bound identity', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'mbforge-patent-'))
  const previousSettings = process.env.MBFORGE_SETTINGS_PATH
  const previousBackend = process.env.MBFORGE_BACKEND_URL
  const requests: Array<{ messages: unknown[]; tools: Array<{ function: { name: string } }> }> = []
  let submitted: Record<string, unknown> | undefined
  const fixture = createServer(async (req, res) => {
    const body = await readBody(req) as Record<string, unknown>
    if (req.url === '/v1/chat/completions') {
      requests.push(body as typeof requests[number])
      if (requests.length === 1) {
        res.writeHead(200, { 'content-type': 'text/event-stream' })
        res.flushHeaders() // Reproduces a provider that keeps its stream open.
        return
      }
      const args = JSON.stringify({ answer: {
        status: 'unanswerable',
        unanswerable_reason: requests.length === 2 ? 'invalid-reason' : 'no_attribution',
      } })
      res.writeHead(200, { 'content-type': 'text/event-stream' })
      for (const [delta, finish] of [
        [{ role: 'assistant', tool_calls: [{ index: 0, id: 'submit', type: 'function', function: { name: 'submit_gap_answer', arguments: args } }] }, null],
        [{}, 'tool_calls'],
      ]) res.write('data: ' + JSON.stringify({ id: 'completion', object: 'chat.completion.chunk', created: 1, model: 'fixture', choices: [{ index: 0, delta, finish_reason: finish }] }) + '\n\n')
      res.end('data: [DONE]\n\n')
    } else if (req.url === '/api/v1/patent-analysis/tools/submit-gap-answer') {
      submitted = body.answer as Record<string, unknown>
      res.setHeader('content-type', 'application/json')
      res.end(JSON.stringify({ success: true, status: 'unanswerable' }))
    } else res.writeHead(404).end()
  })
  const sidecar = createServer(async (req, res) => {
    await handlePatentAnalysis(req, res, await readBody(req))
  })
  const listen = async (server: ReturnType<typeof createServer>) => {
    await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
    return `http://127.0.0.1:${(server.address() as AddressInfo).port}`
  }
  try {
    const fixtureUrl = await listen(fixture)
    const url = await listen(sidecar)
    process.env.MBFORGE_BACKEND_URL = fixtureUrl
    process.env.MBFORGE_SETTINGS_PATH = join(directory, 'settings.json')
    await writeFile(process.env.MBFORGE_SETTINGS_PATH, JSON.stringify({ llm: {
      provider: 'openai_compatible', model: 'fixture', api_key: 'fixture-key', base_url: fixtureUrl + '/v1',
    } }))
    const request = runRequest({
      budget: { ...BUDGET, max_model_turns: 10, request_timeout_seconds: 10, max_total_tokens: 80000 },
      gaps: [
        { gap_id: 'g-1', gap_kind: 'table', code: 'complex_activity_table', evidence_ids: ['e1'], excerpt: 'FIRST_GAP_ONLY' },
        { gap_id: 'g-2', gap_kind: 'table', code: 'complex_activity_table', evidence_ids: ['e2'], excerpt: 'SECOND_GAP_ONLY' },
      ],
    })
    const response = await fetch(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(request) })
    const text = await response.text()
    assert.equal(response.status, 200)
    assert.match(text, /gap time budget exceeded/)
    assert.match(text, /"complete":false/)
    assert.match(text, /"status":"succeeded"/)
    assert.equal(requests.length, 3, 'the invalid answer is repaired once, then submission ends the session')
    const toolFailure = text.split('\n').filter(line => line.startsWith('data: '))
      .map(line => JSON.parse(line.slice(6)) as Record<string, unknown>)
      .find(event => event.kind === 'tool' && event.ok === false)
    assert.ok(toolFailure, 'SDK validation failures must be observable as tool failures')
    assert.match(String(toolFailure.error), /unanswerable_reason/)
    assert.ok(requests.every(r => !r.tools.some(t => t.function.name === 'get_gap')))
    assert.ok(requests.every(r => !r.tools.some(t => t.function.name === 'list_molecules')),
      'table extraction must not spend its budget searching the structure catalogue')
    assert.ok(!JSON.stringify(requests[1].messages).includes('FIRST_GAP_ONLY'))
    assert.equal(submitted?.gap_id, 'g-2')
    assert.equal(submitted?.doc_id, 'doc-1')
    assert.equal(submitted?.attempt_id, 'attempt-1')
    assert.deepEqual(activeAttemptIds(), [])
  } finally {
    for (const server of [fixture, sidecar]) {
      server.closeAllConnections()
      await new Promise<void>(resolve => server.close(() => resolve()))
    }
    if (previousSettings === undefined) delete process.env.MBFORGE_SETTINGS_PATH
    else process.env.MBFORGE_SETTINGS_PATH = previousSettings
    if (previousBackend === undefined) delete process.env.MBFORGE_BACKEND_URL
    else process.env.MBFORGE_BACKEND_URL = previousBackend
    await rm(directory, { recursive: true, force: true })
  }
})
