import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import ChatMarkdown from './chat/ChatMarkdown'
import { useSettings } from '@/api/query/hooks'
import { streamAgentChat, type AgentChatEvent, type AgentLlmConfig } from '@/api/http/agent'
import {
  BeakerIcon,
  BotIcon,
  InfoIcon,
  SendIcon,
  SettingsIcon,
  SparklesIcon,
  UserIcon,
} from '@/components/icons'
import { Button, InlineAlert, Input, PageContainer, PageTitle, TextArea } from './ui'
import './AgentChat.css'

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

function TypingDots({ label }: { label: string }) {
  return (
    <span className="agent-typing" role="status" aria-label={label}>
      <span aria-hidden="true" />
      <span aria-hidden="true" />
      <span aria-hidden="true" />
    </span>
  )
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
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const { data: settings } = useSettings()

  // Seed the config form from the persisted LLM settings once they load.
  useEffect(() => {
    const llm = settings?.settings?.llm
    if (!llm) return
    setConfig((current) => ({
      ...current,
      provider: llm.provider || current.provider,
      model: llm.model || current.model,
      base_url: llm.base_url || current.base_url,
      api_key: llm.api_key && llm.api_key !== '***' ? llm.api_key : current.api_key,
    }))
  }, [settings])

  // Keep the newest message pinned to the bottom as the reply streams in.
  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, activity])

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
    <PageContainer className="agent-page">
      <header className="agent-header">
        <div className="agent-header__title">
          <span className="agent-header__icon" aria-hidden="true">
            <BeakerIcon size={20} />
          </span>
          <div>
            <PageTitle>{t('agent.title')}</PageTitle>
            <p className="agent-header__subtitle">{t('agent.subtitle')}</p>
          </div>
        </div>
        <Button
          size="sm"
          variant="secondary"
          icon={<SettingsIcon size={16} />}
          ariaPressed={showConfig}
          onClick={() => setShowConfig((value) => !value)}
        >
          {showConfig ? t('agent.hideConfig') : t('agent.showConfig')}
        </Button>
      </header>

      {showConfig && (
        <section className="agent-config ui-card" aria-label={t('agent.configTitle')}>
          <div className="agent-config__grid">
            <label className="agent-field" htmlFor="agent-provider">
              <span className="agent-field__label">{t('agent.provider')}</span>
              <Input
                id="agent-provider"
                value={config.provider}
                onChange={(event) => setConfig({ ...config, provider: event.target.value })}
              />
            </label>
            <label className="agent-field" htmlFor="agent-model">
              <span className="agent-field__label">{t('agent.model')}</span>
              <Input
                id="agent-model"
                value={config.model}
                onChange={(event) => setConfig({ ...config, model: event.target.value })}
              />
            </label>
            <label className="agent-field" htmlFor="agent-base-url">
              <span className="agent-field__label">{t('agent.baseUrl')}</span>
              <Input
                id="agent-base-url"
                value={config.base_url}
                onChange={(event) => setConfig({ ...config, base_url: event.target.value })}
                placeholder={t('agent.baseUrlPlaceholder')}
              />
            </label>
            <label className="agent-field" htmlFor="agent-api-key">
              <span className="agent-field__label">{t('agent.apiKey')}</span>
              <Input
                id="agent-api-key"
                type="password"
                value={config.api_key}
                onChange={(event) => setConfig({ ...config, api_key: event.target.value })}
                placeholder={t('agent.apiKeyPlaceholder')}
              />
            </label>
          </div>
          <p className="agent-config__hint">
            <span className="agent-config__hint-icon" aria-hidden="true">
              <InfoIcon size={14} />
            </span>
            <span>{t('agent.keyHint')}</span>
          </p>
        </section>
      )}

      {error && (
        <InlineAlert tone="danger" title={t('agent.error')}>{error}</InlineAlert>
      )}

      <section className="agent-chat ui-card">
        <div
          className="agent-chat__scroll"
          ref={scrollRef}
          role="log"
          aria-live="polite"
          aria-busy={busy}
        >
          {messages.length === 0 ? (
            <div className="agent-empty">
              <span className="agent-empty__icon" aria-hidden="true">
                <SparklesIcon size={24} />
              </span>
              <p className="agent-empty__title">{t('agent.emptyTitle')}</p>
              <p className="agent-empty__hint">{t('agent.empty')}</p>
            </div>
          ) : (
            messages.map((message) => (
              <article key={message.id} className={`agent-msg agent-msg--${message.role}`}>
                <span className="agent-msg__avatar" aria-hidden="true">
                  {message.role === 'user' ? <UserIcon size={15} /> : <BotIcon size={15} />}
                </span>
                <div className="agent-msg__body">
                  <span className="agent-msg__role">
                    {message.role === 'user' ? t('agent.you') : t('agent.assistant')}
                  </span>
                  <div className="agent-msg__bubble">
                    {message.role === 'user'
                      ? message.content
                      : message.content
                        ? <ChatMarkdown content={message.content} />
                        : busy ? <TypingDots label={t('agent.thinking')} /> : null}
                  </div>
                </div>
              </article>
            ))
          )}
        </div>

        {activity && (
          <div className="agent-activity" aria-live="polite">
            <span className="agent-activity__dot" aria-hidden="true" />
            <span>{activity}</span>
          </div>
        )}

        <div className="agent-composer">
          <div className="agent-composer__box">
            <TextArea
              className="agent-composer__input"
              ariaLabel={t('agent.composerPlaceholder')}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void send() } }}
              placeholder={t('agent.composerPlaceholder')}
              rows={2}
              maxHeight={160}
            />
            {busy
              ? <Button variant="danger" onClick={stop}>{t('agent.stop')}</Button>
              : <Button variant="primary" icon={<SendIcon size={16} />} onClick={() => void send()} disabled={!draft.trim()}>{t('agent.send')}</Button>}
          </div>
          <span className="agent-composer__hint">{t('agent.composerHint')}</span>
        </div>
      </section>
    </PageContainer>
  )
}
