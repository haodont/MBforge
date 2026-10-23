/** Offline contract against the installed official extension and its real SDK. */
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createRequire } from 'node:module'
import { createServer } from 'node:http'
import axios from 'axios'
import { SessionManager, type ExtensionToolContext } from '@earendil-works/pi-coding-agent'
import { createWebTools } from './web.js'
import { createSessionForSpec } from './session.js'
import { readBody } from './http.js'

test('official Tavily tools respect per-turn limits, sources, secrets and cancellation', async () => {
  const key = 'tvly-offline-key-never-persist'
  const oldEnv = process.env.TAVILY_API_KEY
  process.env.TAVILY_API_KEY = 'unrelated-process-key'
  const cjsAxios = createRequire(import.meta.url)('axios') as typeof axios
  const adapters = [axios.defaults.adapter, cjsAxios.defaults.adapter]
  const calls: string[] = []
  let modelCalls = 0
  const provider = createServer(async (request, response) => {
    await readBody(request)
    modelCalls++
    const toolName = modelCalls === 1 ? 'web_search' : 'web_fetch'
    const args = modelCalls === 1 ? { query: 'MRGPRX2 antagonists' } : { urls: ['https://example.org/paper'], query: 'MRGPRX2' }
    const delta = modelCalls <= 2 ? { tool_calls: [{ index: 0, id: 'call-' + modelCalls, type: 'function', function: { name: toolName, arguments: JSON.stringify(args) } }] } : { content: 'Read [Paper](https://example.org/paper).' }
    response.writeHead(200, { 'content-type': 'text/event-stream' })
    for (const [part, finish] of [[{ role: 'assistant', ...delta }, null], [{}, modelCalls <= 2 ? 'tool_calls' : 'stop']] as const) {
      response.write('data: ' + JSON.stringify({ id: 'completion', object: 'chat.completion.chunk', created: 1, model: 'offline', choices: [{ index: 0, delta: part, finish_reason: finish }] }) + '\n\n')
    }
    response.end('data: [DONE]\n\n')
  })
  await new Promise<void>(resolve => provider.listen(0, '127.0.0.1', resolve))
  const address = provider.address()
  assert.ok(address && typeof address === 'object')
  let fail = false
  let wait = false
  const adapter: typeof axios.defaults.adapter = async request => {
    assert.equal(request.headers.get('Authorization'), 'Bearer ' + key)
    const body = JSON.parse(request.data as string) as Record<string, unknown>
    calls.push(request.url ?? '')
    if (fail) throw new Error('Rejected ' + key)
    if (wait) await new Promise<void>(resolve => setTimeout(resolve, 100))
    const data = request.url?.endsWith('/search')
      ? { query: body.query, images: [], results: [{ url: 'https://example.org/paper', title: 'Paper', content: 'Evidence' }], response_time: 0 }
      : { results: [{ url: 'https://example.org/paper', raw_content: 'x'.repeat(6000) }], failed_results: [], response_time: 0 }
    return { data, status: 200, statusText: 'OK', headers: {}, config: request }
  }
  axios.defaults.adapter = adapter
  cjsAxios.defaults.adapter = adapter
  let session: Awaited<ReturnType<typeof createSessionForSpec>> | undefined
  try {
    assert.equal((await createWebTools({ enabled: false, apiKey: key })).extensions, undefined)
    const web = await createWebTools({ enabled: true, apiKey: key })
    session = await createSessionForSpec({ provider: 'openai', model: 'offline', apiKey: 'offline', baseUrl: `http://127.0.0.1:${address.port}/v1`, maxTokens: 100, requestTimeoutMs: 1000 }, {
      systemPrompt: 'Offline test', toolNames: web.toolNames, customTools: [], extensions: web.extensions,
    })
    assert.deepEqual(session.getAllTools().map(tool => tool.name).sort(), ['web_fetch', 'web_search'])
    web.reset('Research MRGPRX2')
    await session.prompt('Research MRGPRX2', { expandPromptTemplates: false, source: 'rpc' })
    assert.equal(modelCalls, 3)
    assert.equal(session.agent.state.errorMessage, undefined)
    assert.ok(!JSON.stringify(session.messages).includes(key))
    assert.match(JSON.stringify(session.messages), /Read \[Paper\]/)
    calls.length = 0
    const tools = web.extensions!.extensions[0].tools
    const ctx = { hasUI: false, sessionManager: SessionManager.inMemory() } as unknown as ExtensionToolContext
    const search = () => tools.get('web_search')!.definition.execute('search', { query: 'MRGPRX2 antagonists' }, undefined, undefined, ctx)
    const fetchPage = (url: string, signal?: AbortSignal) => tools.get('web_fetch')!.definition.execute('fetch', { urls: [url], query: 'MRGPRX2' }, signal, undefined, ctx)
    web.reset('Explain evidence')
    await assert.rejects(fetchPage('https://example.org/unseen'), /supplied by the user/)
    assert.equal(calls.length, 0)
    const searched = await search()
    assert.match(JSON.stringify(searched), /retrieved_at/)
    const fetched = await fetchPage('https://example.org/paper')
    assert.equal((fetched.details as { results: Array<{ content: string; truncated: boolean }> }).results[0].content.length, 5000)
    assert.equal((fetched.details as { results: Array<{ truncated: boolean }> }).results[0].truncated, true)
    for (let i = 0; i < 3; i++) await search()
    await assert.rejects(search(), /4-search limit/)
    web.reset('New question')
    await assert.rejects(fetchPage('https://example.org/paper'), /supplied by the user/)
    web.reset('Read https://example.org/paper')
    for (let i = 0; i < 3; i++) await fetchPage('https://example.org/paper')
    await assert.rejects(fetchPage('https://example.org/paper'), /3-fetch limit/)
    web.reset('Read https://example.org/paper')
    await search()
    await assert.rejects(fetchPage('https://127.0.0.1/'), /public HTTPS/)
    fail = true
    await assert.rejects(search(), error => error instanceof Error && !error.message.includes(key))
    fail = false; wait = true
    const controller = new AbortController()
    const pending = fetchPage('https://example.org/paper', controller.signal)
    controller.abort()
    await assert.rejects(pending, /abort/i)
    assert.equal(process.env.TAVILY_API_KEY, 'unrelated-process-key')
  } finally {
    session?.dispose()
    provider.closeAllConnections()
    await new Promise<void>(resolve => provider.close(() => resolve()))
    axios.defaults.adapter = adapters[0]
    cjsAxios.defaults.adapter = adapters[1]
    if (oldEnv === undefined) delete process.env.TAVILY_API_KEY
    else process.env.TAVILY_API_KEY = oldEnv
  }
})
