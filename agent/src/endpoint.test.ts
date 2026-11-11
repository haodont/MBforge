// @tested-functions normalizeBaseUrl, parseTokenCount, saveCustomEndpoint, readCustomEndpoint, discoverModels
import assert from 'node:assert/strict'
import { once } from 'node:events'
import { createServer } from 'node:http'
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'

import { ModelRuntime } from '@earendil-works/pi-coding-agent'

import {
  CUSTOM_PROVIDER_ID,
  discoverModels,
  normalizeBaseUrl,
  parseTokenCount,
  readCustomEndpoint,
  saveCustomEndpoint,
} from './endpoint.js'

test('custom endpoint saves provider metadata separately from the key and stays loadable by pi', async () => {
  const agentDir = mkdtempSync(join(tmpdir(), 'mbforge-endpoint-'))
  const modelsPath = join(agentDir, 'models.json')
  const authPath = join(agentDir, 'auth.json')

  writeFileSync(
    modelsPath,
    JSON.stringify(
      {
        providers: {
          existing: {
            baseUrl: 'https://existing.example/v1',
            api: 'openai-completions',
            models: [],
          },
        },
      },
      null,
      2,
    ),
  )
  writeFileSync(
    authPath,
    JSON.stringify(
      { existing: { type: 'api_key', key: 'existing-key' } },
      null,
      2,
    ),
  )

  assert.equal(
    normalizeBaseUrl(' https://gateway.example/v1/ '),
    'https://gateway.example/v1',
  )
  assert.throws(() => normalizeBaseUrl('ftp://gateway.example'), /http/)
  assert.equal(parseTokenCount('128k', 'Context window'), 128_000)
  assert.equal(parseTokenCount('1.5m', 'Context window'), 1_500_000)
  assert.throws(() => parseTokenCount('0', 'Context window'), /positive/)

  const saved = saveCustomEndpoint(
    {
      baseUrl: 'https://gateway.example/v1/',
      api: 'openai-completions',
      modelId: 'acme-chat',
      modelName: 'Acme Chat',
      contextWindow: 200_000,
      maxTokens: 16_384,
      apiKey: 'sk-custom',
    },
    agentDir,
  )
  assert.equal(saved.modelsPath, modelsPath)
  assert.equal(saved.authPath, authPath)
  assert.equal(saved.providerId, CUSTOM_PROVIDER_ID)

  const models = JSON.parse(readFileSync(modelsPath, 'utf8')) as {
    providers: Record<string, Record<string, unknown>>
  }
  const auth = JSON.parse(readFileSync(authPath, 'utf8')) as {
    existing: { key: string }
    custom: { type: string; key: string }
  }
  assert.equal(models.providers.custom.baseUrl, 'https://gateway.example/v1')
  assert.equal(models.providers.custom.api, 'openai-completions')
  assert.equal(models.providers.custom.authHeader, true)
  assert.equal(models.providers.custom.apiKey, undefined)
  assert.deepEqual(
    (
      models.providers.custom.models as Array<{
        id: string
        name: string
        contextWindow: number
        maxTokens: number
      }>
    ).map((model) => [
      model.id,
      model.name,
      model.contextWindow,
      model.maxTokens,
    ]),
    [['acme-chat', 'Acme Chat', 200_000, 16_384]],
  )
  assert.equal(auth.existing.key, 'existing-key')
  assert.deepEqual(auth.custom, { type: 'api_key', key: 'sk-custom' })

  const current = readCustomEndpoint(agentDir)
  assert.equal(current.baseUrl, 'https://gateway.example/v1')
  assert.equal(current.api, 'openai-completions')
  assert.equal(current.modelId, 'acme-chat')
  assert.equal(current.modelName, 'Acme Chat')
  assert.equal(current.contextWindow, 200_000)
  assert.equal(current.maxTokens, 16_384)
  assert.equal(current.hasKey, true)

  saveCustomEndpoint(
    {
      baseUrl: 'https://gateway.example/v1',
      api: 'openai-completions',
      modelId: 'acme-chat',
      contextWindow: 256_000,
      maxTokens: 32_768,
    },
    agentDir,
  )
  const updated = JSON.parse(readFileSync(modelsPath, 'utf8')) as {
    providers: Record<
      string,
      { models: Array<{ contextWindow: number; maxTokens: number }> }
    >
  }
  assert.equal(updated.providers.custom.models[0].contextWindow, 256_000)
  assert.equal(updated.providers.custom.models[0].maxTokens, 32_768)
  const kept = JSON.parse(readFileSync(authPath, 'utf8')) as {
    custom: { type: string; key: string }
  }
  assert.equal(kept.custom.key, 'sk-custom')

  assert.throws(
    () =>
      saveCustomEndpoint(
        {
          baseUrl: 'https://gateway.example/v1',
          api: 'openai-completions',
          modelId: 'acme-chat',
          contextWindow: 8_192,
          maxTokens: 16_384,
        },
        agentDir,
      ),
    /cannot exceed/,
  )

  const runtime = await ModelRuntime.create({
    authPath,
    modelsPath,
    refreshOnCreate: false,
    allowModelNetwork: false,
  })
  assert.equal(runtime.getError(), undefined)
  const model = runtime.getModel(CUSTOM_PROVIDER_ID, 'acme-chat')
  assert.ok(model)
  const resolved = await runtime.getAuth(model)
  assert.equal(resolved?.auth.apiKey, 'sk-custom')
})

test('model discovery reads /v1/models, carries auth, and extracts context limits', async (t) => {
  const requested: string[] = []
  let authorization: string | undefined
  const server = createServer((request, response) => {
    requested.push(request.url ?? '')
    authorization = request.headers.authorization
    if (request.url !== '/v1/models') {
      response.writeHead(404)
      response.end()
      return
    }
    response.writeHead(200, { 'content-type': 'application/json' })
    response.end(
      JSON.stringify({
        data: [
          {
            id: 'acme-small',
            context_window: 32_000,
            max_output_tokens: 4_096,
          },
          {
            id: 'acme-large',
            context_length: 200_000,
            max_completion_tokens: 16_384,
          },
        ],
      }),
    )
  })
  const listening = once(server, 'listening')
  server.listen(0, '127.0.0.1')
  await listening
  t.after(async () => {
    const closed = once(server, 'close')
    server.closeAllConnections()
    server.close()
    await closed
  })
  const address = server.address()
  assert.ok(address && typeof address === 'object')

  const models = await discoverModels(
    `http://127.0.0.1:${address.port}`,
    'openai-completions',
    'sk-test',
  )

  assert.deepEqual(requested, ['/models', '/v1/models'])
  assert.equal(authorization, 'Bearer sk-test')
  assert.deepEqual(models, [
    { id: 'acme-small', contextWindow: 32_000, maxTokens: 4_096 },
    { id: 'acme-large', contextWindow: 200_000, maxTokens: 16_384 },
  ])
})

test('model discovery fills missing limits from /v1/models/{model}', async (t) => {
  const requests: Array<{ url: string; authorization: string | undefined }> = []
  const server = createServer((request, response) => {
    requests.push({
      url: request.url ?? '',
      authorization: request.headers.authorization,
    })
    const url = request.url ?? ''
    if (url === '/v1/models') {
      response.writeHead(200, { 'content-type': 'application/json' })
      response.end(
        JSON.stringify({
          data: [
            { id: 'acme-small' },
            { id: 'acme-large' },
            { id: 'acme-missing' },
          ],
        }),
      )
      return
    }
    if (url === '/v1/models/acme-small') {
      response.writeHead(200, { 'content-type': 'application/json' })
      response.end(
        JSON.stringify({ context_length: 200_000, max_tokens: 16_384 }),
      )
      return
    }
    if (url === '/v1/models/acme-large') {
      response.writeHead(200, { 'content-type': 'application/json' })
      response.end(
        JSON.stringify({
          data: { context_window: 128_000, max_completion_tokens: 8_192 },
        }),
      )
      return
    }
    response.writeHead(404)
    response.end()
  })
  const listening = once(server, 'listening')
  server.listen(0, '127.0.0.1')
  await listening
  t.after(async () => {
    const closed = once(server, 'close')
    server.closeAllConnections()
    server.close()
    await closed
  })
  const address = server.address()
  assert.ok(address && typeof address === 'object')

  const models = await discoverModels(
    `http://127.0.0.1:${address.port}/v1`,
    'openai-completions',
    'sk-test',
  )

  assert.deepEqual(
    requests.map((request) => request.url).sort(),
    [
      '/v1/models',
      '/v1/models/acme-large',
      '/v1/models/acme-missing',
      '/v1/models/acme-small',
    ],
  )
  assert.ok(requests.every((request) => request.authorization === 'Bearer sk-test'))
  assert.deepEqual(models, [
    { id: 'acme-small', contextWindow: 200_000, maxTokens: 16_384 },
    { id: 'acme-large', contextWindow: 128_000, maxTokens: 8_192 },
    { id: 'acme-missing' },
  ])
})
