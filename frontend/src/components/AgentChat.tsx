import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import ChatMarkdown from './chat/ChatMarkdown'
import { getSettings } from '@/api/http/settings'
import { streamAgentChat, type AgentChatEvent, type AgentLlmConfig } from '@/api/http/agent'
import { Button, InlineAlert, Input, PageContainer, PageTitle, TextArea } from './ui'

interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
}

const initialConfig: AgentLlmConfig = {
  provider: 'openai_compatible',
  model: 'gpt-4o-mini',
  api_key: '',
  base_url: '',
}

function messageId(): string {
  return typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`
}

export default function AgentChat() {
  const { t } = useTranslation()
  const [config, setConfig] = useState<AgentLlmConfig>(initialConfig)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [draft, setDraft] = useState('')
  const [sessionId, setSessionId] = useState<string>()
  const [busy, setBusy] = useState(false)
  const [showConfig, setShowConfig] = useState(true)
  const [activity, setActivity] = useState('')
  const [error, setError] = useState<string>()
  const abortRef = useRef<AbortController | undefined>(undefined)

  useEffect(() => {
    let cancelled = false
    void getSettings().then((response) => {
      if (cancelled || !response.settings?.llm) return
      const llm = response.settings.llm
      setConfig((current) => ({
        ...current,
        provider: llm.provider || current.provider,
        model: llm.model || current.model,
        base_url: llm.base_url || current.base_url,
        api_key: llm.api_key && llm.api_key !== '***' ? llm.api_key : current.api_key,
      }))
    })
    return () => { cancelled = true }
  }, [])

  const updateAssistant = (id: string, content: string) => {
    setMessages((current) => current.map((item) => item.id === id ? { ...item, content } : item))
  }

  const handleEvent = (assistantId: string, event: AgentChatEvent) => {
    const text = event.data.text
    if (event.type === 'delta' && typeof text === 'string') {
      setMessages((current) => current.map((item) => item.id === assistantId
        ? { ...item, content: item.content + text }
        : item))
    } else if (event.type === 'tool') {
      const name = typeof event.data.name === 'string' ? event.data.name : 'tool'
      const statusText =
        typeof event.data.status === 'string'
          ? event.data.status
          : JSON.stringify(event.data.status ?? '')
      setActivity(`${name}: ${statusText}`)
    } else if (event.type === 'error') {
      setError(typeof event.data.message === 'string' ? event.data.message : t('agent.error'))
    }
  }

  const send = async () => {
    const message = draft.trim()
    if (!message || busy) return
    setDraft('')
    setError(undefined)
    setActivity('')
    setBusy(true)
    const assistantId = messageId()
    setMessages((current) => [
      ...current,
      { id: messageId(), role: 'user', content: message },
      { id: assistantId, role: 'assistant', content: '' },
    ])
    const controller = new AbortController()
    abortRef.current = controller
    try {
      const result = await streamAgentChat(
        { message, session_id: sessionId, config },
        (event) => handleEvent(assistantId, event),
        controller.signal,
      )
      if (result.sessionId) setSessionId(result.sessionId)
    } catch (reason) {
      if (!controller.signal.aborted) {
        const detail = reason instanceof Error ? reason.message : String(reason)
        setError(detail)
        updateAssistant(assistantId, t('agent.requestFailed'))
      }
    } finally {
      abortRef.current = undefined
      setBusy(false)
      setActivity('')
    }
  }

  const stop = () => abortRef.current?.abort()

  return (
    <PageContainer>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 'var(--space-4)' }}>
        <div>
          <PageTitle style={{ marginBottom: 'var(--space-1)' }}>{t('agent.title')}</PageTitle>
          <p style={{ color: 'var(--text-secondary)', fontSize: 'var(--text-sm)' }}>{t('agent.subtitle')}</p>
        </div>
        <Button size="sm" variant="secondary" onClick={() => setShowConfig((value) => !value)}>
          {showConfig ? t('agent.hideConfig') : t('agent.showConfig')}
        </Button>
      </div>

      {showConfig && (
        <div className="ui-card" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 'var(--space-3)', marginTop: 'var(--space-4)', padding: 'var(--space-3)' }}>
          <label>
            <span>{t('agent.provider')}</span>
            <Input value={config.provider} onChange={(event) => setConfig({ ...config, provider: event.target.value })} />
          </label>
          <label>
            <span>{t('agent.model')}</span>
            <Input value={config.model} onChange={(event) => setConfig({ ...config, model: event.target.value })} />
          </label>
          <label>
            <span>{t('agent.baseUrl')}</span>
            <Input value={config.base_url} onChange={(event) => setConfig({ ...config, base_url: event.target.value })} placeholder={t('agent.baseUrlPlaceholder')} />
          </label>
          <label>
            <span>{t('agent.apiKey')}</span>
            <Input type="password" value={config.api_key} onChange={(event) => setConfig({ ...config, api_key: event.target.value })} placeholder={t('agent.apiKeyPlaceholder')} />
          </label>
          <p style={{ gridColumn: '1 / -1', color: 'var(--text-muted)', fontSize: 'var(--text-xs)' }}>{t('agent.keyHint')}</p>
        </div>
      )}

      {error && <InlineAlert tone="danger" title={t('agent.error')} style={{ marginTop: 'var(--space-3)' }}>{error}</InlineAlert>}

      <div className="ui-card" style={{ display: 'flex', minHeight: 0, flex: 1, flexDirection: 'column', gap: 'var(--space-3)', marginTop: 'var(--space-4)', padding: 'var(--space-4)' }}>
        <div style={{ minHeight: 0, flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
          {messages.length === 0 && <p style={{ color: 'var(--text-muted)' }}>{t('agent.empty')}</p>}
          {messages.map((message) => (
            <div key={message.id} style={{ alignSelf: message.role === 'user' ? 'flex-end' : 'stretch', maxWidth: message.role === 'user' ? '80%' : '100%' }}>
              <div style={{ color: 'var(--text-muted)', fontSize: 'var(--text-xs)', marginBottom: 'var(--space-1)' }}>
                {message.role === 'user' ? t('agent.you') : t('agent.assistant')}
              </div>
              {message.role === 'user' ? (
                <div style={{ padding: 'var(--space-2) var(--space-3)', borderRadius: 'var(--radius-md)', background: 'var(--accent-light)', whiteSpace: 'pre-wrap' }}>{message.content}</div>
              ) : (
                <ChatMarkdown content={message.content || (busy ? '…' : '')} />
              )}
            </div>
          ))}
        </div>
        {activity && <div style={{ color: 'var(--text-muted)', fontSize: 'var(--text-xs)' }}>{activity}</div>}
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 'var(--space-2)', padding: 'var(--space-2)', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)' }}>
          <TextArea value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void send() } }} placeholder={t('agent.placeholder')} rows={2} maxHeight={160} />
          {busy ? <Button variant="danger" onClick={stop}>{t('agent.stop')}</Button> : <Button variant="primary" onClick={() => void send()} disabled={!draft.trim()}>{t('agent.send')}</Button>}
        </div>
      </div>
    </PageContainer>
  )
}
