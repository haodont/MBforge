import { afterEach, describe, expect, it, vi } from 'vitest'
import { streamAgentChat } from '../agent'

describe('streamAgentChat', () => {
  afterEach(() => vi.restoreAllMocks())

  it('keeps split SSE frames intact and returns the session id', async () => {
    const encoder = new TextEncoder()
    let index = 0
    const chunks = [
      encoder.encode('event: delta\ndata: {"text":"hel'),
      encoder.encode('lo"}\n\nevent: done\ndata: {"session_id":"s-1"}\n\n'),
    ]
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      body: {
        getReader: () => ({
          read: () => index < chunks.length
            ? Promise.resolve({ done: false, value: chunks[index++] })
            : Promise.resolve({ done: true, value: undefined }),
          releaseLock: vi.fn(),
        }),
      },
    }))

    const events: string[] = []
    const result = await streamAgentChat(
      {
        message: 'find ethanol',
        config: { provider: 'openai_compatible', model: 'demo', api_key: 'key', base_url: '' },
      },
      (event) => events.push(`${event.type}:${JSON.stringify(event.data)}`),
    )

    expect(events).toEqual([
      'delta:{"text":"hello"}',
      'done:{"session_id":"s-1"}',
    ])
    expect(result).toEqual({ sessionId: 's-1' })
  })
})
