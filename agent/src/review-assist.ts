/** Review-center AI assistance: one bounded call per review item.
 *
 * The review center is where the deterministic pipeline already refused to
 * decide, so the reviewer is handed the printed text and the original images and
 * asked one question. The answer is a suggestion: Python stores it beside the
 * item and a human still decides. This module owns the provider call, exactly
 * like every other LLM call in MBForge.
 */

import { type IncomingMessage, type ServerResponse } from 'node:http'

import { sendJson } from './http.js'
import {
  asRecord,
  defaultBaseUrl,
  describeFetchError,
  loadPersistedSettings,
  providerKind,
  sanitizeError,
  stringValue,
} from './llm.js'

export interface AssistImage {
  media_type?: string
  data_base64: string
  label?: string
}

export interface AssistConfig {
  provider: string
  model: string
  apiKey: string
  baseUrl: string
  maxTokens: number
  timeoutMs: number
}

export const ASSIST_SYSTEM = [
  '你是专利复核助手。你会收到一段专利原文、可选的原页图像与结构裁剪图，以及若干已识别候选结构。',
  '只依据给出的内容回答，不要发明结构、数值或编号。',
  '无法确定时第一行必须写 answer=cannot_decide。',
].join('')

function clampNumber(value: unknown, fallback: number, min: number, max: number): number {
  return typeof value === 'number' && Number.isFinite(value)
    ? Math.min(max, Math.max(min, value))
    : fallback
}

export function readAssistConfig(raw: Record<string, unknown>): AssistConfig {
  const provider = stringValue(raw.provider, 'openai_compatible', 80).toLowerCase()
  providerKind(provider)
  const model = stringValue(raw.model, '', 256)
  if (!model) throw new Error('no assist model configured')
  const apiKey = stringValue(
    raw.api_key ?? raw.apiKey,
    provider === 'ollama' ? 'ollama' : '',
    4096,
  )
  if (provider !== 'ollama' && !apiKey) {
    throw new Error('an API key is required for the configured assist provider')
  }
  const baseUrl = stringValue(
    raw.base_url ?? raw.baseUrl,
    defaultBaseUrl(provider),
    2048,
  ).replace(/\/$/, '')
  return {
    provider,
    model,
    apiKey,
    baseUrl,
    maxTokens: Math.round(clampNumber(raw.max_tokens ?? raw.maxTokens, 2048, 256, 8192)),
    timeoutMs: Math.round(clampNumber(raw.request_timeout, 120, 5, 600) * 1000),
  }
}

function clip(value: unknown, limit: number): string {
  const text = typeof value === 'string' ? value : ''
  return text.length <= limit ? text : text.slice(0, limit) + '...(truncated)'
}

export function assistPrompt(packet: Record<string, unknown>): string {
  const parts: string[] = [clip(packet.question, 4000)]
  const candidates = Array.isArray(packet.candidates) ? packet.candidates : []
  if (candidates.length > 0) {
    parts.push('\n候选结构（只能从中选择候选编号）：')
    candidates.slice(0, 16).forEach((value, index) => {
      const candidate = asRecord(value)
      const name = stringValue(candidate.name, '', 80)
      const smiles = stringValue(candidate.smiles, '', 600)
      parts.push(
        String(index + 1) +
          '. mol_id=' +
          stringValue(candidate.mol_id, '(未分配)', 200) +
          (name ? ' name=' + name : '') +
          (smiles ? ' smiles=' + smiles : ''),
      )
    })
  }
  parts.push('\n原文（页码与证据号在方括号内）：\n' + clip(packet.text, 12000))
  return parts.join('\n')
}
function ollamaBase(baseUrl: string): string {
  const base = baseUrl.replace(/\/+$/, '')
  return base.endsWith('/v1') ? base.slice(0, -3) : base
}

export function buildAssistRequest(
  config: AssistConfig,
  prompt: string,
  images: AssistImage[],
): { url: string; headers: Record<string, string>; body: Record<string, unknown> } {
  if (config.provider === 'anthropic') {
    const base = config.baseUrl || defaultBaseUrl('anthropic')
    const url = base.endsWith('/v1') ? base + '/messages' : base + '/v1/messages'
    const content: Record<string, unknown>[] = images.map(image => ({
      type: 'image',
      source: {
        type: 'base64',
        media_type: stringValue(image.media_type, 'image/png', 40),
        data: image.data_base64,
      },
    }))
    content.push({ type: 'text', text: prompt })
    return {
      url,
      headers: {
        'content-type': 'application/json',
        'x-api-key': config.apiKey,
        'anthropic-version': '2023-06-01',
      },
      body: {
        model: config.model,
        max_tokens: config.maxTokens,
        system: ASSIST_SYSTEM,
        messages: [{ role: 'user', content }],
      },
    }
  }
  if (config.provider === 'ollama') {
    return {
      url: ollamaBase(config.baseUrl) + '/api/chat',
      headers: { 'content-type': 'application/json' },
      body: {
        model: config.model,
        stream: false,
        messages: [
          { role: 'system', content: ASSIST_SYSTEM },
          {
            role: 'user',
            content: prompt,
            images: images.map(image => image.data_base64),
          },
        ],
      },
    }
  }
  const url = (config.baseUrl || defaultBaseUrl('openai_compatible')) + '/chat/completions'
  const content: Record<string, unknown>[] = [{ type: 'text', text: prompt }]
  for (const image of images) {
    content.push({
      type: 'image_url',
      image_url: {
        url:
          'data:' +
          stringValue(image.media_type, 'image/png', 40) +
          ';base64,' +
          image.data_base64,
      },
    })
  }
  return {
    url,
    headers: {
      'content-type': 'application/json',
      authorization: 'Bearer ' + config.apiKey,
    },
    body: {
      model: config.model,
      max_tokens: config.maxTokens,
      messages: [
        { role: 'system', content: ASSIST_SYSTEM },
        { role: 'user', content },
      ],
    },
  }
}

export function extractAnswer(provider: string, payload: Record<string, unknown>): string {
  if (provider === 'anthropic') {
    const blocks = Array.isArray(payload.content) ? payload.content : []
    return blocks
      .map(block => stringValue(asRecord(block).text, '', 8000))
      .filter(Boolean)
      .join('\n')
  }
  if (provider === 'ollama') {
    return stringValue(asRecord(payload.message).content, '', 8000)
  }
  const choices = Array.isArray(payload.choices) ? payload.choices : []
  const message = asRecord(asRecord(choices[0]).message)
  const content = message.content
  if (Array.isArray(content)) {
    return content
      .map(part => stringValue(asRecord(part).text, '', 8000))
      .filter(Boolean)
      .join('\n')
  }
  return stringValue(content, '', 8000)
}

/** Vision goes to a dedicated vision model when one is configured, else to the
 *  chat model: LongCat accepts text+image, so images need no second entry. */
function assistSettings(settings: Record<string, unknown>): Record<string, unknown> {
  const vision = asRecord(settings.vlm)
  return stringValue(vision.model, '', 256) !== '' ? vision : asRecord(settings.llm)
}

/** A provider that cannot take images answers with a content-type complaint. */
export function shouldRetryWithoutImages(status: number, detail: string): boolean {
  if (![400, 413, 415, 422].includes(status)) return false
  return /image|vision|multimodal|content[\s-]?type|unsupported|invalid_request/i.test(detail)
}

interface AssistCallResult {
  transport: boolean
  status: number
  ok: boolean
  answer: string
  error: string
}

async function callProvider(
  config: AssistConfig,
  prompt: string,
  images: AssistImage[],
): Promise<AssistCallResult> {
  const requestBody = buildAssistRequest(config, prompt, images)
  try {
    const upstream = await fetch(requestBody.url, {
      method: 'POST',
      headers: requestBody.headers,
      body: JSON.stringify(requestBody.body),
      signal: AbortSignal.timeout(config.timeoutMs),
    })
    if (!upstream.ok) {
      const detail = sanitizeError(await upstream.text(), config.apiKey).slice(0, 300)
      return {
        transport: false,
        status: upstream.status,
        ok: false,
        answer: '',
        error: 'HTTP ' + upstream.status + ': ' + detail,
      }
    }
    const payload = asRecord(await upstream.json())
    const answer = extractAnswer(config.provider, payload).trim()
    if (!answer) {
      return {
        transport: false,
        status: 200,
        ok: false,
        answer: '',
        error: 'the model returned no text',
      }
    }
    return { transport: false, status: 200, ok: true, answer, error: '' }
  } catch (error) {
    return {
      transport: true,
      status: 0,
      ok: false,
      answer: '',
      error: describeFetchError(error),
    }
  }
}

export async function handleReviewAssist(
  request: IncomingMessage,
  response: ServerResponse,
  body: unknown,
): Promise<void> {
  const packet = asRecord(asRecord(body).packet)
  const images = (Array.isArray(packet.images) ? packet.images : []).slice(0, 4).map(asRecord)
  const settings = await loadPersistedSettings()
  const raw = assistSettings(settings)

  let config: AssistConfig
  try {
    config = readAssistConfig(raw)
  } catch (error) {
    sendJson(request, response, 200, {
      status: 'unavailable',
      model: '',
      vision: false,
      answer: '',
      error: sanitizeError(error, ''),
    })
    return
  }

  const prompt = assistPrompt(packet)
  const payloads: AssistImage[] = images.map(image => ({
    media_type: stringValue(image.media_type, 'image/png', 40),
    data_base64: stringValue(image.data_base64, '', 4_000_000),
  }))
  let vision = payloads.length > 0
  let result = await callProvider(config, prompt, vision ? payloads : [])
  if (!result.ok && vision && shouldRetryWithoutImages(result.status, result.error)) {
    // The configured model cannot take images after all: answer from the text
    // and report that the drawing was not seen, instead of failing the item.
    vision = false
    result = await callProvider(config, prompt, [])
  }

  if (!result.ok) {
    sendJson(request, response, 200, {
      status: result.transport ? 'unavailable' : 'error',
      model: config.model,
      vision: false,
      answer: '',
      error: result.error,
    })
    return
  }

  sendJson(request, response, 200, {
    status: /cannot_decide/i.test(result.answer) ? 'refused' : 'answered',
    model: config.model,
    vision,
    answer: result.answer.slice(0, 8000),
    error: '',
  })
}
