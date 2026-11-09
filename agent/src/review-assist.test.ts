/** Offline contract for review-center AI assistance: no provider is contacted. */
import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  assistPrompt,
  buildAssistRequest,
  extractAnswer,
  readAssistConfig,
  shouldRetryWithoutImages,
} from './review-assist.js'

const IMAGE = { media_type: 'image/png', data_base64: 'AAAA' }

function config(provider: string, baseUrl: string) {
  return { provider, model: 'm', apiKey: 'k', baseUrl, maxTokens: 256, timeoutMs: 1000 }
}

test('the original image reaches every provider in its own shape', () => {
  const openai = buildAssistRequest(config('openai_compatible', 'https://api.example/v1'), 'Q', [IMAGE])
  assert.equal(openai.url, 'https://api.example/v1/chat/completions')
  const content = openai.body.messages as Array<{ role: string; content: unknown }>
  assert.equal(content[0].role, 'system')
  const parts = content[1].content as Array<Record<string, any>>
  assert.equal(parts[0].type, 'text')
  assert.equal(parts[1].type, 'image_url')
  assert.equal(parts[1].image_url.url, 'data:image/png;base64,AAAA')

  const anthropic = buildAssistRequest(config('anthropic', 'https://api.anthropic.com'), 'Q', [IMAGE])
  assert.equal(anthropic.url, 'https://api.anthropic.com/v1/messages')
  assert.equal(anthropic.headers['x-api-key'], 'k')
  const blocks = (anthropic.body.messages as Array<{ content: Array<Record<string, any>> }>)[0].content
  assert.deepEqual(blocks[0], { type: 'image', source: { type: 'base64', media_type: 'image/png', data: 'AAAA' } })
  assert.equal(blocks[1].type, 'text')

  const ollama = buildAssistRequest(config('ollama', 'http://127.0.0.1:11434/v1'), 'Q', [IMAGE])
  assert.equal(ollama.url, 'http://127.0.0.1:11434/api/chat')
  const messages = ollama.body.messages as Array<Record<string, any>>
  assert.deepEqual(messages[1].images, ['AAAA'])
})

test('the prompt offers only the candidates the model may choose from', () => {
  const prompt = assistPrompt({
    question: '哪一个是化合物17？',
    candidates: [
      { mol_id: 'm-1', name: '17', smiles: 'CCO' },
      { mol_id: 'm-2', name: '', smiles: 'CCN' },
    ],
    text: '[p86 12345678] 实施例17：目标化合物17的制备',
  })
  assert.match(prompt, /哪一个是化合物17？/)
  assert.match(prompt, /1\. mol_id=m-1 name=17 smiles=CCO/)
  assert.match(prompt, /2\. mol_id=m-2 smiles=CCN/)
  assert.match(prompt, /实施例17/)
})

test('an answer is read from each provider response shape', () => {
  assert.equal(
    extractAnswer('openai_compatible', { choices: [{ message: { content: 'answer=m-1' } }] }),
    'answer=m-1',
  )
  assert.equal(
    extractAnswer('anthropic', { content: [{ type: 'text', text: 'answer=cannot_decide' }] }),
    'answer=cannot_decide',
  )
  assert.equal(extractAnswer('ollama', { message: { content: 'answer=m-2' } }), 'answer=m-2')
})

test('a provider that rejects images is retried text-only, not failed', () => {
  assert.equal(shouldRetryWithoutImages(400, 'HTTP 400: unknown content type image_url'), true)
  assert.equal(shouldRetryWithoutImages(422, 'invalid_request: vision unsupported'), true)
  assert.equal(shouldRetryWithoutImages(500, 'HTTP 500: upstream exploded'), false)
  assert.equal(shouldRetryWithoutImages(400, 'rate limit exceeded'), false)
})

test('a missing assist model is a reported configuration error', () => {
  assert.throws(() => readAssistConfig({}), /no assist model configured/)
  assert.throws(
    () => readAssistConfig({ model: 'm', provider: 'openai_compatible' }),
    /API key/, 
  )
})