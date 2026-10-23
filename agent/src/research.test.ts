/** Local HTTP contract: durable Pi history restores without replaying task tools. */
import assert from 'node:assert/strict'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { createServer, type Server } from 'node:http'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { test } from 'node:test'
import { handleResearchChat } from './research.js'
import { readBody } from './http.js'

async function listen(server: Server): Promise<string> {
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  const address = server.address()
  assert.ok(address && typeof address === 'object')
  return `http://127.0.0.1:${address.port}`
}

test('research restores Pi messages without replaying actions or storing runtime secrets', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'mbforge-research-'))
  const sessionFile = join(directory, 'research.jsonl')
  const credential = 'private-turn-credential-do-not-store'
  const apiKey = 'private-provider-key-do-not-store'
  const tavilyKey = 'test-tavily-key-do-not-store'
  const oldSettings = process.env.MBFORGE_SETTINGS_PATH
  const oldBackend = process.env.MBFORGE_BACKEND_URL
  const requests: Array<{ messages: Array<{ role: string; content: unknown }>; tools: Array<{ function: { name: string } }> }> = []
  let taskStarts = 0
  let question = 'Analyze selected patent'
  const fixture = createServer(async (req, res) => {
    const body = await readBody(req)
    if (req.url === '/v1/chat/completions') {
      requests.push(body as typeof requests[number])
      if (question === 'Fail safely') {
        res.writeHead(401, { 'content-type': 'application/json' })
        res.end(JSON.stringify({ error: { message: `Rejected ${apiKey}`, type: 'authentication_error' } }))
        return
      }
      res.writeHead(200, { 'content-type': 'text/event-stream' })
      const toolCall = requests.length === 1
      const delta = toolCall ? { tool_calls: [{ index: 0, id: 'task-call-1', type: 'function', function: { name: 'start_patent_analysis', arguments: '{"doc_ids":["doc-1"]}' } }] } : { content: requests.length === 2 ? 'Queued the selected patent.' : 'The previous task remains queued.' }
      res.write('data: ' + JSON.stringify({ id: 'completion', object: 'chat.completion.chunk', created: 1, model: 'local-fixture', choices: [{ index: 0, delta: { role: 'assistant', ...delta }, finish_reason: null }] }) + '\n\n')
      res.write('data: ' + JSON.stringify({ id: 'completion', object: 'chat.completion.chunk', created: 1, model: 'local-fixture', choices: [{ index: 0, delta: {}, finish_reason: toolCall ? 'tool_calls' : 'stop' }] }) + '\n\n')
      res.end('data: [DONE]\n\n')
    } else if (req.url === '/api/v1/research/runtime/spec') {
      assert.deepEqual(body, { credential })
      res.setHeader('content-type', 'application/json')
      res.end(JSON.stringify({ session_id: 'session-1', session_file: sessionFile, message: question,
        context: { document_ids: ['doc-1'], molecule_refs: [], task_refs: [], allow_patent_analysis: question.startsWith('Analyze') }, history: [] }))
    } else if (req.url === '/api/v1/research/runtime/start-patent-analysis') {
      assert.deepEqual(body, { credential, doc_ids: ['doc-1'] })
      taskStarts++
      res.setHeader('content-type', 'application/json')
      res.end(JSON.stringify({ references: [{ task_id: 'task-1', run_id: 'run-1', doc_id: 'doc-1' }] }))
    } else {
      res.writeHead(404).end()
    }
  })
  const sidecar = createServer(async (req, res) => {
    await handleResearchChat(req, res, await readBody(req))
  })
  try {
    const fixtureUrl = await listen(fixture)
    const sidecarUrl = await listen(sidecar)
    process.env.MBFORGE_BACKEND_URL = fixtureUrl
    process.env.MBFORGE_SETTINGS_PATH = join(directory, 'settings.json')
    const settingsPath = process.env.MBFORGE_SETTINGS_PATH
    await writeFile(settingsPath, JSON.stringify({
      llm: { provider: 'openai_compatible', model: 'local-fixture', api_key: apiKey, base_url: fixtureUrl + '/v1' },
      web_search: { enabled: true, api_key: tavilyKey },
    }))
    const turn = async () => {
      const response = await fetch(sidecarUrl, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ credential }) })
      assert.equal(response.status, 200)
      return response.text()
    }
    const first = await turn()
    assert.match(first, /event: task/)
    assert.match(first, /event: done/)
    assert.equal(taskStarts, 1)
    question = 'Explain the existing task'
    const second = await turn()
    assert.match(second, /event: done/)
    assert.doesNotMatch(second, /event: task/)
    assert.equal(taskStarts, 1)
    assert.equal(requests.length, 3)
    assert.ok(requests[0].tools.some(tool => tool.function.name === 'load_skill'))
    assert.ok(requests[0].tools.some(tool => tool.function.name === 'search_structures'))
    assert.ok(requests[0].tools.some(tool => tool.function.name === 'search_papers'))
    assert.ok(requests[2].messages.some(message => message.role === 'assistant' && message.content === 'Queued the selected patent.'))
    assert.ok(requests[2].messages.some(message => message.role === 'tool'))
    assert.ok(requests.every(request => !request.tools.some(tool => ['bash', 'read', 'write', 'edit', 'library_sql'].includes(tool.function.name))))
    question = 'Fail safely'
    await writeFile(settingsPath, JSON.stringify({
      llm: { provider: 'openai_compatible', model: 'local-fixture', api_key: apiKey, base_url: fixtureUrl + '/v1' },
      web_search: { enabled: false, api_key: tavilyKey },
    }))
    const failed = await turn()
    assert.match(failed, /event: error/)
    assert.ok(!failed.includes(apiKey))
    assert.ok(!requests[3].tools.some(tool => ['search_structures', 'search_papers'].includes(tool.function.name)))
    const recorded = await readFile(sessionFile, 'utf8')
    assert.match(recorded, /Queued the selected patent/)
    for (const secret of [credential, apiKey, tavilyKey]) {
      assert.ok(!recorded.includes(secret))
      assert.ok(!JSON.stringify(requests).includes(secret))
    }
  } finally {
    for (const server of [fixture, sidecar]) {
      server.closeAllConnections()
      await new Promise<void>(resolve => server.close(() => resolve()))
    }
    if (oldSettings === undefined) delete process.env.MBFORGE_SETTINGS_PATH
    else process.env.MBFORGE_SETTINGS_PATH = oldSettings
    if (oldBackend === undefined) delete process.env.MBFORGE_BACKEND_URL
    else process.env.MBFORGE_BACKEND_URL = oldBackend
    await rm(directory, { recursive: true, force: true })
  }
})
