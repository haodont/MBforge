/** Fixed official Pi extension, with MBForge settings and per-turn boundaries. */
import { DefaultResourceLoader, SettingsManager, type LoadExtensionsResult } from '@earendil-works/pi-coding-agent'
import { Type } from '@earendil-works/pi-ai'
import { isIP } from 'node:net'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { createRequire } from 'node:module'
import { asRecord, loadPersistedSettings, sanitizeError } from './llm.js'

export interface WebConfig { enabled: boolean; apiKey: string }
export async function loadWebConfig(): Promise<WebConfig> {
  const config = asRecord((await loadPersistedSettings()).web_search)
  const apiKey = typeof config.api_key === 'string' ? config.api_key.trim() : ''
  return { enabled: config.enabled === true && !!apiKey && apiKey !== '***', apiKey }
}

function publicUrl(value: string): string | undefined {
  try {
    const url = new URL(value)
    const host = url.hostname.toLowerCase()
    if (url.protocol !== 'https:' || url.username || url.password || url.port ||
      isIP(host) || host.startsWith('[') || !host.includes('.') ||
      /(^|\.)(localhost|local|internal|test|invalid)$/.test(host)) return undefined
    url.hash = ''
    return url.href
  } catch { return undefined }
}

export async function createWebTools(config: WebConfig): Promise<{
  extensions?: LoadExtensionsResult
  toolNames: string[]
  reset: (message: string) => void
}> {
  const allowedUrls = new Set<string>()
  let searches = 0
  let fetches = 0
  const reset = (message: string) => {
    searches = 0; fetches = 0; allowedUrls.clear()
    for (const match of message.matchAll(/https:\/\/[^\s<>"\])}]+/g)) {
      const url = publicUrl(match[0]); if (url) allowedUrls.add(url)
    }
  }
  if (!config.enabled) return { toolNames: [], reset }
  const pluginPath = join(dirname(createRequire(import.meta.url).resolve('@tavily/pi-extension/package.json')), 'index.ts')
  const loader = new DefaultResourceLoader({
    cwd: tmpdir(), agentDir: join(tmpdir(), 'mbforge-controlled-pi'),
    settingsManager: SettingsManager.inMemory({}),
    noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
    additionalExtensionPaths: [pluginPath], systemPrompt: '', appendSystemPrompt: [],
  })
  await loader.reload()
  const extensions = loader.getExtensions()
  if (extensions.errors.length || extensions.extensions.length !== 1) throw new Error('Could not load the official Tavily Pi extension')
  const extension = extensions.extensions[0]
  for (const name of ['web_search', 'web_fetch']) {
    const registered = extension.tools.get(name)
    if (!registered) throw new Error('Missing Tavily tool: ' + name)
    const upstream = registered.definition
    registered.definition = {
      ...upstream,
      promptGuidelines: [],
      description: name === 'web_search'
        ? 'Search public web information with short public keywords when local evidence is insufficient. Returns snippets and actual source URLs, not verified full text.'
        : 'Read relevant text from HTTPS URLs supplied by the user or returned by web_search this turn. Provide a public topic query. Up to 3 URLs per call.',
      parameters: name === 'web_search'
        ? Type.Object({ query: Type.String({ minLength: 1, maxLength: 400 }), max_results: Type.Optional(Type.Integer({ minimum: 1, maximum: 5 })) }, { additionalProperties: false })
        : Type.Object({ urls: Type.Array(Type.String({ maxLength: 2048 }), { minItems: 1, maxItems: 3 }), query: Type.String({ minLength: 1, maxLength: 400 }) }, { additionalProperties: false }),
      async execute(id, rawParams, signal, _update, ctx) {
        const params = asRecord(rawParams)
        if (signal?.aborted) throw new Error('Web research aborted')
        const query = String(params.query).trim()
        if (!query || query.length > 400) throw new Error('Use 1-400 characters of public search keywords')
        let input: Record<string, unknown>
        if (name === 'web_search') {
          if (++searches > 4) throw new Error('This turn reached its 4-search limit')
          input = { query, max_results: Math.min(5, Math.max(1, Number(params.max_results) || 5)), search_depth: 'advanced', chunks_per_source: 2, include_answer: false, include_raw_content: false, include_images: false, auto_parameters: false }
        } else {
          const urls = (params.urls as string[]).map(url => publicUrl(url))
          if (!urls.length || urls.length > 3 || urls.some(url => !url || !allowedUrls.has(url))) throw new Error('Fetch only public HTTPS URLs supplied by the user or returned by this turn’s search')
          if (++fetches > 3) throw new Error('This turn reached its 3-fetch limit')
          input = { urls, query, chunks_per_source: 2, extract_depth: 'basic', format: 'text', include_images: false, timeout: 20 }
        }
        const timeout = AbortSignal.timeout(30000)
        const requestSignal = signal ? AbortSignal.any([signal, timeout]) : timeout
        try {
          let pending: ReturnType<typeof upstream.execute>
          const previous = process.env.TAVILY_API_KEY
          // Pinned extension captures the key synchronously before its first await.
          try {
            process.env.TAVILY_API_KEY = config.apiKey
            pending = upstream.execute(id, input, requestSignal, undefined, ctx)
          } finally {
            if (previous === undefined) delete process.env.TAVILY_API_KEY
            else process.env.TAVILY_API_KEY = previous
          }
          const reply = await pending
          const details = asRecord(reply.details)
          const results = (Array.isArray(details.results) ? details.results : []).slice(0, name === 'web_search' ? 5 : 3).map(value => {
            const row = asRecord(value)
            const url = typeof row.url === 'string' ? publicUrl(row.url) : undefined
            if (url) allowedUrls.add(url)
            const raw = String(row.raw_content ?? row.content ?? '')
            return { url, title: String(row.title ?? '').slice(0, 300), content: raw.slice(0, 5000), truncated: raw.length > 5000, published_date: typeof row.published_date === 'string' ? row.published_date.slice(0, 64) : undefined }
          })
          const failedResults = (Array.isArray(details.failed_results) ? details.failed_results : []).slice(0, 3).map(value => {
            const row = asRecord(value)
            return { url: String(row.url ?? '').slice(0, 2048), error: String(row.error ?? '').slice(0, 300) }
          })
          const credits = asRecord(details.usage).credits
          const payload = { source: 'web', retrieved_at: new Date().toISOString(), results, failed_results: failedResults, usage: typeof credits === 'number' && Number.isFinite(credits) ? { credits } : undefined }
          const text = JSON.stringify(payload).split(config.apiKey).join('***')
          return { content: [{ type: 'text', text }], details: JSON.parse(text) as unknown }
        } catch (error) { throw new Error(sanitizeError(error, config.apiKey)) }
      },
    }
  }
  return { extensions, toolNames: ['web_search', 'web_fetch'], reset }
}
