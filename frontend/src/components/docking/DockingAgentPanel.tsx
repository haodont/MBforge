import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import ChatMarkdown from '../chat/ChatMarkdown'
import { showToast } from '@/hooks/useToast'
import { useSettings } from '@/api/query/hooks'
import { streamAgentChat, type AgentChatEvent, type AgentLlmConfig } from '@/api/http/agent'
import { BotIcon, SendIcon, XIcon, UserIcon } from '@/components/icons'
import { Button, TextArea } from '@/components/ui'

interface Message {
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

interface Props {
  /** Injected into every message so the agent knows the current docking context. */
  contextHint?: string
}

/** Compact chat rail for the docking page (shares the agent sidecar stream). */
export default function DockingAgentPanel({ contextHint }: Props) {
  const { t } = useTranslation()
  const [config, setConfig] = useState<AgentLlmConfig>(initialConfig)
  const [messages, setMessages] = useState<Message[]>([])
  const [draft, setDraft] = useState('')
  const [sessionId, setSessionId] = useState<string>()
  const [busy, setBusy] = useState(false)
  const [activity, setActivity] = useState('')
  const abortRef = useRef<AbortController | undefined>(undefined)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const { data: settings } = useSettings()

  // Seed the config from the persisted LLM settings once they load.
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

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, activity])

  const send = async () => {
    const text = draft.trim()
    if (!text || busy) return
    setDraft('')
    setBusy(true)
    setActivity('')
    const assistantId = messageId()
    setMessages((current) => [
      ...current,
      { id: messageId(), role: 'user', content: text },
      { id: assistantId, role: 'assistant', content: '' },
    ])
    const controller = new AbortController()
    abortRef.current = controller
    const message = contextHint ? `[对接上下文] ${contextHint}\n\n${text}` : text
    try {
      const result = await streamAgentChat(
        { message, session_id: sessionId, config },
        (event: AgentChatEvent) => {
          if (event.type === 'delta' && typeof event.data.text === 'string') {
            setMessages((current) => current.map((item) => item.id === assistantId
              ? { ...item, content: item.content + (event.data.text as string) }
              : item))
          } else if (event.type === 'tool') {
            const name = typeof event.data.name === 'string' ? event.data.name : 'tool'
            setActivity(name)
          }
        },
        controller.signal,
      )
      if (result.sessionId) setSessionId(result.sessionId)
    } catch (reason) {
      if (!controller.signal.aborted) {
        showToast(reason instanceof Error ? reason.message : String(reason), 'error')
      }
    } finally {
      abortRef.current = undefined
      setBusy(false)
      setActivity('')
    }
  }

  return (
    <div className="docking-agent">
      <div className="docking-agent__log" ref={scrollRef} role="log" aria-live="polite">
        {messages.length === 0 && (
          <p className="docking-agent__empty">{t('docking.agentEmpty')}</p>
        )}
        {messages.map((message) => (
          <div key={message.id} className={`docking-agent__msg docking-agent__msg--${message.role}`}>
            <span className="docking-agent__avatar" aria-hidden="true">
              {message.role === 'user' ? <UserIcon size={13} /> : <BotIcon size={13} />}
            </span>
            <div className="docking-agent__bubble">
              {message.role === 'user'
                ? message.content
                : <ChatMarkdown content={message.content || '…'} />}
            </div>
          </div>
        ))}
      </div>
      {activity && <div className="docking-agent__activity">{activity}…</div>}
      <div className="docking-agent__composer">
        <TextArea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void send() } }}
          placeholder={t('docking.agentPlaceholder')}
          ariaLabel={t('docking.agentPlaceholder')}
          rows={2}
          maxHeight={120}
        />
        {busy
          ? <Button variant="danger" size="sm" icon={<XIcon size={14} />} onClick={() => abortRef.current?.abort()}>{t('agent.stop')}</Button>
          : <Button variant="primary" size="sm" icon={<SendIcon size={14} />} onClick={() => void send()} disabled={!draft.trim()}>{t('agent.send')}</Button>}
      </div>
    </div>
  )
}
