import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import ChatMarkdown from './chat/ChatMarkdown'
import { useDocuments, useIngestQueue, useSettings } from '@/api/query/hooks'
import { useMolecule, useMoleculePage } from '@/api/query/hooks/useMolecules'
import { readArtifactReference, readTaskReference, streamResearchChat } from '@/api/http/research'
import { useCreateResearchSession, useDeleteResearchSession, useImportResearchHistory, useLoadResearchSession, useResearchSession, useResearchSessions } from '@/api/query/hooks/useResearch'
import { useAppContext } from '@/context/AppContext'
import { BotIcon, FileTextIcon, PlusIcon, SendIcon, SettingsIcon, SparklesIcon, UserIcon, XIcon } from '@/components/icons'
import { Badge, Button, Chip, IconButton, InlineAlert, Input, Modal, Tabs, TextArea } from './ui'
import { historyKey, readHistory } from './research/history'
import type { ResearchArtifactReference, ResearchMessage, ResearchMoleculeReference, ResearchSession, ResearchTaskReference, ResearchSessionSummary } from '@/api/http/research'
import { ResearchArtifactCard, ResearchTaskPanel } from './research/ResearchReferences'
import './AgentChat.css'

const newId = () => crypto.randomUUID()
const MoleculeDetailDrawer = lazy(() => import('./molecule/MoleculeDetailDrawer'))

export default function AgentChat() {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const { libraryRoot, researchDocumentIds, setResearchDocumentIds, openTab } = useAppContext()
  const { data: settings, isError: settingsError } = useSettings()
  const docs = useDocuments()
  const queue = useIngestQueue(libraryRoot)
  const [active, setActive] = useState<ResearchSession | null>(null)
  const history = useResearchSessions(libraryRoot)
  const storedSession = useResearchSession(libraryRoot, active?.id ?? null)
  const createSession = useCreateResearchSession(libraryRoot)
  const loadSession = useLoadResearchSession(libraryRoot)
  const importHistory = useImportResearchHistory(libraryRoot)
  const deleteSession = useDeleteResearchSession(libraryRoot)
  const [deleteCandidate, setDeleteCandidate] = useState<ResearchSessionSummary | null>(null)
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [historyActionError, setHistoryActionError] = useState('')
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [activity, setActivity] = useState('')
  const [error, setError] = useState('')
  const [migrationError, setMigrationError] = useState(false)
  const [legacyHistory] = useState(() => {
    try { return localStorage.getItem(historyKey(libraryRoot) + ':imported') ? [] : readHistory(libraryRoot) }
    catch { return readHistory(libraryRoot) }
  })
  const migrationStarted = useRef(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [contextOpen, setContextOpen] = useState(false)
  const [documentSearch, setDocumentSearch] = useState('')
  const [moleculeSearch, setMoleculeSearch] = useState('')
  const [debouncedMoleculeSearch, setDebouncedMoleculeSearch] = useState('')
  const [taskSearch, setTaskSearch] = useState('')
  const [contextTab, setContextTab] = useState<'documents' | 'molecules' | 'tasks'>('documents')
  const [moleculeRefs, setMoleculeRefs] = useState<ResearchMoleculeReference[]>([])
  const [taskRefs, setTaskRefs] = useState<ResearchTaskReference[]>([])
  const [viewedMoleculeId, setViewedMoleculeId] = useState<string | null>(null)
  const viewedMolecule = useMolecule(libraryRoot, viewedMoleculeId)
  const moleculePage = useMoleculePage(contextOpen && contextTab === 'molecules' ? libraryRoot : null, {
    page: 1, pageSize: 20, activityPresence: 'all', query: debouncedMoleculeSearch,
    sortField: 'name', sortDirection: 'asc',
  })
  const abortRef = useRef<AbortController | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const followRef = useRef(true)
  const sessions = history.data ?? []
  const messages = active?.messages ?? []
  const documents = docs.data?.documents ?? []
  const selected = documents.filter(doc => researchDocumentIds.includes(doc.doc_id))
  const contextCount = selected.length + moleculeRefs.length + taskRefs.length
  const llm = settings?.settings?.llm
  const configured = Boolean(llm?.model && (llm.api_key || llm.provider === 'ollama'))

  const importLocalHistory = importHistory.mutateAsync
  useEffect(() => {
    if (!history.isSuccess || migrationStarted.current || !legacyHistory.length) return
    migrationStarted.current = true
    void importLocalHistory(legacyHistory).then(() => {
      try { localStorage.setItem(historyKey(libraryRoot) + ':imported', 'true') } catch { /* SQL remains authoritative; imports are idempotent. */ }
    }).catch(() => setMigrationError(true))
  }, [history.isSuccess, importLocalHistory, legacyHistory, libraryRoot])

  useEffect(() => {
    if (!busy && storedSession.data && storedSession.data.id === active?.id && storedSession.data !== active) setActive(storedSession.data)
  }, [busy, storedSession.data, active])

  useEffect(() => () => {
    abortRef.current?.abort()
  }, [libraryRoot])

  useEffect(() => {
    const el = scrollRef.current
    if (el && followRef.current) el.scrollTop = el.scrollHeight
  }, [active, activity])

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedMoleculeSearch(moleculeSearch.trim()), 250)
    return () => window.clearTimeout(timer)
  }, [moleculeSearch])

  const updateMessage = (id: string, patch: Partial<ResearchMessage>, delta?: string) => {
    setActive(current => current ? {
      ...current, updatedAt: Date.now(), messages: current.messages.map(message => message.id !== id ? message
        : { ...message, ...patch, content: delta === undefined ? patch.content ?? message.content : message.content + delta }),
    } : current)
  }

  const send = async (allowAnalysis = false) => {
    const question = draft.trim() || (allowAnalysis ? t('research.analysisPrompt') : '')
    if (!question || abortRef.current || messages.some(message => message.status === 'pending')) return
    if (messages.length >= 200) { setError(t('research.historyLimit')); return }
    if (question.length > 20_000) { setError(t('research.messageTooLong')); return }
    const assistantId = newId()
    const requestId = newId()
    const newMessages: ResearchMessage[] = [
      { id: newId(), request_id: requestId, role: 'user', content: question },
      { id: assistantId, request_id: requestId, role: 'assistant', content: '', status: 'pending' },
    ]
    setError('')
    setActivity('')
    setBusy(true)
    followRef.current = true
    const controller = new AbortController()
    abortRef.current = controller
    const responseState = { terminal: false }
    let session: ResearchSession | null = null
    const receivedTasks: ResearchTaskReference[] = []
    const receivedArtifacts: ResearchArtifactReference[] = []
    try {
      const saved = active ?? await createSession.mutateAsync(t('research.new'))
      controller.signal.throwIfAborted()
      session = { ...saved, documentIds: selected.map(doc => doc.doc_id), moleculeRefs, taskRefs }
      setActive({ ...session, title: saved.messages.length ? saved.title : question.slice(0, 48), messages: [...saved.messages, ...newMessages] })
      setDraft('')
      await streamResearchChat(libraryRoot, session, requestId, question, allowAnalysis, event => {
        if (controller.signal.aborted) return
        if (event.type === 'delta' && typeof event.data.text === 'string') updateMessage(assistantId, {}, event.data.text)
        if (event.type === 'tool') {
          const key = 'research.tool.' + String(event.data.name)
          const name = i18n.exists(key) ? t(key) : t('research.toolGeneric')
          const statusKey = 'research.toolStatus.' + String(event.data.status)
          setActivity(name + ' · ' + (i18n.exists(statusKey) ? t(statusKey) : t('research.toolStatus.start')))
        }
        if (event.type === 'task') {
          const reference = readTaskReference(event.data.reference)
          if (reference && !receivedTasks.some(item => item.task_id === reference.task_id)) {
            receivedTasks.push(reference)
            updateMessage(assistantId, { taskRefs: [...receivedTasks] })
            void queue.refetch()
          }
        }
        if (event.type === 'artifact') {
          const reference = readArtifactReference(event.data.reference)
          if (reference) {
            receivedArtifacts.splice(0, receivedArtifacts.length, ...receivedArtifacts.filter(item => item.doc_id !== reference.doc_id), reference)
            updateMessage(assistantId, { artifactRefs: [...receivedArtifacts] })
          }
        }
        if (event.type === 'done') {
          responseState.terminal = true
          const status = event.data.status === 'stopped' || event.data.status === 'failed' ? event.data.status : 'complete'
          updateMessage(assistantId, { status, ...(typeof event.data.text === 'string' ? { content: event.data.text } : {}) })
        }
        if (event.type === 'error') {
          responseState.terminal = true
          setError(typeof event.data.message === 'string' ? event.data.message : t('agent.error'))
          updateMessage(assistantId, { status: 'failed' })
        }
      }, controller.signal)
      if (!responseState.terminal && !controller.signal.aborted) throw new Error(t('research.streamInterrupted'))
    } catch (reason) {
      if (!controller.signal.aborted) {
        setError(reason instanceof Error ? reason.message : String(reason))
        updateMessage(assistantId, { status: 'failed' })
      }
    } finally {
      if (controller.signal.aborted) updateMessage(assistantId, { status: 'stopped' })
      if (session) {
        try { setActive(await loadSession.mutateAsync(session.id)) }
        catch { setError(t('research.historyError')) }
        void history.refetch()
      }
      abortRef.current = null
      setBusy(false)
      setActivity('')
    }
  }

  const newResearch = () => {
    if (busy) return
    setActive(null)
    setDraft('')
    setError('')
    setResearchDocumentIds([])
    setMoleculeRefs([])
    setTaskRefs([])
    followRef.current = true
  }

  const openSource = (docId: string, page?: number) => {
    const doc = documents.find(item => item.doc_id === docId)
    if (!doc || (page !== undefined && (!Number.isSafeInteger(page) || page > doc.page_count))) {
      setError(t('research.sourceUnavailable'))
      return
    }
    openTab({ type: 'pdf', title: doc.title || doc.file_name, libraryRoot, initialPage: page,
      doc: { doc_id: doc.doc_id, path: doc.file_name, doc_type: 'pdf', title: doc.title || doc.file_name } })
  }

  const openAnalysis = (doc: (typeof documents)[number]) => openTab({ type: 'pdf', title: doc.title || doc.file_name, libraryRoot, initialSidePaneTab: 'analysis',
    doc: { doc_id: doc.doc_id, path: doc.file_name, doc_type: 'pdf', title: doc.title || doc.file_name } })

  const restoreHistory = async (id: string) => {
    if (busy || loadingHistory) return
    setLoadingHistory(true)
    setHistoryActionError('')
    try {
      const session = await loadSession.mutateAsync(id)
      setActive(session); setDraft(''); setError(''); setHistoryOpen(false); setResearchDocumentIds(session.documentIds ?? [])
      setMoleculeRefs(session.moleculeRefs ?? []); setTaskRefs(session.taskRefs ?? []); followRef.current = true
    } catch { setHistoryActionError(t('research.historyError')) }
    finally { setLoadingHistory(false) }
  }

  return (
    <section className="research-chat" aria-label={t('research.workspace')}>
      <header className="research-chat__header">
        <div><span className="research-eyebrow">{t('research.workspace')}</span><h1>{active?.title ?? t('research.new')}</h1></div>
        <div className="research-chat__actions">
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => setHistoryOpen(true)}>{t('research.history')}</Button>
          <Button size="sm" icon={<PlusIcon size={15} />} disabled={busy} onClick={newResearch}>{t('research.new')}</Button>
        </div>
      </header>
      <div className="research-chat__scroll" ref={scrollRef} role="log" aria-live="polite" aria-busy={busy}
        onScroll={() => { const el = scrollRef.current; if (el) followRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80 }}>
        {messages.length === 0 ? (
          <div className="research-welcome">
            <span className="research-welcome__icon"><SparklesIcon size={28} /></span>
            <span className="research-eyebrow">{t('research.kicker')}</span>
            <h2>{t('research.headline')}</h2>
            <p>{t('research.intro')}</p>
            <div className="research-prompts">
              {['overview', 'activity', 'molecule'].map(key => (
                <Button key={key} variant="ghost" className="research-prompt" disabled={busy} onClick={() => setDraft(t('research.prompt.' + key))}>
                  <span>{t('research.promptTitle.' + key)}</span><small>{t('research.prompt.' + key)}</small>
                </Button>
              ))}
            </div>
          </div>
        ) : messages.map(message => (
          <article key={message.id} className={'research-message research-message--' + message.role}>
            <span className="research-message__avatar">{message.role === 'user' ? <UserIcon size={16} /> : <BotIcon size={16} />}</span>
            <div className="research-message__body">
              <span className="research-message__role">{t(message.role === 'user' ? 'agent.you' : 'agent.assistant')}</span>
              {message.content ? message.role === 'assistant' ? <ChatMarkdown content={message.content} onDocumentLink={openSource} onMoleculeLink={setViewedMoleculeId} /> : <p>{message.content}</p>
                : busy && message.id === messages[messages.length - 1]?.id ? <p className="research-thinking">{t('agent.thinking')}</p> : null}
              {message.status === 'stopped' || message.status === 'failed' || (message.status === 'pending' && !busy) ? <Badge tone={message.status === 'failed' ? 'danger' : 'neutral'}>{t('research.reply.' + message.status)}</Badge> : null}
              {!!message.taskRefs?.length && <div className="research-message__references">{message.taskRefs.map(reference => <ResearchTaskPanel key={reference.task_id}
                reference={reference} documents={documents} tasks={queue.data} pending={queue.isPending} failed={queue.isError} libraryRoot={libraryRoot} onOpen={openAnalysis} />)}</div>}
              {!!message.artifactRefs?.length && <div className="research-message__references">{message.artifactRefs.map(reference => <ResearchArtifactCard key={reference.doc_id + ':' + reference.run_id}
                reference={reference} documents={documents} libraryRoot={libraryRoot} onOpen={openAnalysis} />)}</div>}
            </div>
          </article>
        ))}
        {taskRefs.length > 0 && <section className="research-task-contexts" aria-label={t('research.task.contextReferences')}>
          {taskRefs.map(reference => <ResearchTaskPanel key={reference.task_id} reference={reference} documents={documents} tasks={queue.data}
            pending={queue.isPending} failed={queue.isError} libraryRoot={libraryRoot} onOpen={openAnalysis} />)}
        </section>}
      </div>
      <div className="research-composer">
        {error && <InlineAlert tone="danger">{error}</InlineAlert>}
        {migrationError && <InlineAlert tone="warning">{t('research.migrationError')} <Button size="sm" onClick={() => {
          void importLocalHistory(legacyHistory).then(() => setMigrationError(false)).catch(() => setMigrationError(true))
        }}>{t('research.retry')}</Button></InlineAlert>}
        {(settingsError || settings?.success === false) && <InlineAlert tone="warning">{t('research.settingsError')}</InlineAlert>}
        {activity && <p className="research-activity" role="status">{activity}</p>}
        <div className="research-composer__surface">
          {contextCount > 0 && <div className="research-context-chips">{selected.map(doc => (
            <Button key={doc.doc_id} variant="secondary" size="sm" title={doc.file_name} disabled={busy} icon={<XIcon size={12} />}
              onClick={() => setResearchDocumentIds(ids => ids.filter(id => id !== doc.doc_id))}>{doc.title || doc.file_name}</Button>
          ))}{moleculeRefs.map(reference => (
            <span key={reference.mol_id} className="research-context-molecule">
              <Button variant="secondary" size="sm" title={reference.mol_id} onClick={() => setViewedMoleculeId(reference.mol_id)}>{reference.name}</Button>
              <IconButton size={28} disabled={busy} ariaLabel={t('research.removeMolecule', { name: reference.name })}
                onClick={() => setMoleculeRefs(refs => refs.filter(item => item.mol_id !== reference.mol_id))}><XIcon size={12} /></IconButton>
            </span>
          ))}{taskRefs.map(reference => {
            const doc = documents.find(item => item.doc_id === reference.doc_id)
            const task = queue.data?.find(item => item.id === reference.task_id)
            const stage = task?.stage ?? reference.stage
            const label = `${doc?.title || doc?.file_name || reference.doc_id} · ${stage ? t('pdfPipeline.stage.' + stage) : reference.run_id.slice(0, 8)}`
            return <Button key={reference.task_id} variant="secondary" size="sm" title={reference.run_id} disabled={busy} icon={<XIcon size={12} />}
              onClick={() => setTaskRefs(refs => refs.filter(item => item.task_id !== reference.task_id))}>{label}</Button>
          })}</div>}
          <TextArea value={draft} onChange={event => setDraft(event.target.value)} className="research-composer__input"
            placeholder={t('research.placeholder')} ariaLabel={t('research.placeholder')} rows={3} maxHeight={180}
            onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send() } }} />
          <div className="research-composer__toolbar">
            <Button variant="ghost" size="sm" disabled={busy} icon={<FileTextIcon size={15} />} onClick={() => setContextOpen(true)}>{t('research.context')}{contextCount ? ` · ${contextCount}` : ''}</Button>
            {selected.length > 0 && <Button variant="ghost" size="sm" disabled={busy || messages.some(message => message.status === 'pending')} title={t('research.askAnalyzeHint')}
              onClick={() => void send(true)}>{t('research.askAnalyze')}</Button>}
            <Button variant="ghost" size="sm" icon={<SettingsIcon size={14} />} onClick={() => void navigate('/settings')} title={t('research.modelSettings')}>
              <span className={'research-model-dot' + (configured ? ' is-configured' : '')} />{llm?.model || t('research.modelUnconfirmed')}
            </Button>
            <span className="research-composer__spacer" />
            {busy ? <Button variant="secondary" size="sm" onClick={() => abortRef.current?.abort()}>{t('research.stopReply')}</Button>
              : <Button variant="primary" size="sm" disabled={!draft.trim() || messages.some(message => message.status === 'pending')} icon={<SendIcon size={15} />} onClick={() => void send()}>{t('agent.send')}</Button>}
          </div>
        </div>
        <p className="research-composer__hint">{t('research.composerHint')}</p>
        <Button variant="ghost" size="sm" onClick={() => void navigate('/settings')}>
          {t(settings?.settings?.web_search?.enabled && settings.settings.web_search.api_key ? 'research.webAvailable' : 'research.webUnavailable')}
        </Button>
      </div>
      {viewedMoleculeId && (viewedMolecule.data
        ? <Suspense fallback={<Modal open onClose={() => setViewedMoleculeId(null)} title={t('research.moleculeDetails')}><p>{t('research.loading')}</p></Modal>}>
          <MoleculeDetailDrawer open molecule={viewedMolecule.data} libraryRoot={libraryRoot} onClose={() => setViewedMoleculeId(null)} onSaved={() => void viewedMolecule.refetch()} />
        </Suspense>
        : <Modal open onClose={() => setViewedMoleculeId(null)} title={t('research.moleculeDetails')}>
          {viewedMolecule.isPending ? <p>{t('research.loading')}</p> : <InlineAlert tone="danger">{t('research.moleculeUnavailable')}{viewedMolecule.isError && <Button onClick={() => void viewedMolecule.refetch()}>{t('research.retry')}</Button>}</InlineAlert>}
        </Modal>)}
      <Modal open={historyOpen} onClose={() => setHistoryOpen(false)} title={t('research.history')} maxWidth={600}>
        <p className="research-muted">{t('research.historyHint')}</p>
        {historyActionError && <InlineAlert tone="danger">{historyActionError}</InlineAlert>}
        {history.isPending ? <p>{t('research.loading')}</p> : history.isError ? <InlineAlert tone="danger">{t('research.historyError')} <Button onClick={() => void history.refetch()}>{t('research.retry')}</Button></InlineAlert>
          : sessions.length === 0 && <p className="research-muted">{t('research.noHistory')}</p>}
        {sessions.map(session => <div key={session.id} className="research-history-row"><Button variant="ghost" className="research-history-item" disabled={loadingHistory || busy}
          onClick={() => void restoreHistory(session.id)}><span>{session.title}</span><small>{new Date(session.updatedAt).toLocaleString(i18n.language)}</small></Button>
          <IconButton size={28} disabled={busy} ariaLabel={t('research.deleteResearch', { name: session.title })} onClick={() => { setHistoryOpen(false); setDeleteCandidate(session); setHistoryActionError('') }}><XIcon size={14} /></IconButton>
        </div>)}
      </Modal>
      <Modal open={deleteCandidate !== null} onClose={() => { setDeleteCandidate(null); setHistoryOpen(true) }} title={t('research.deleteResearchTitle')}
        footer={<Button variant="danger" loading={deleteSession.isPending} onClick={() => {
          if (!deleteCandidate) return
          const id = deleteCandidate.id
          void deleteSession.mutateAsync(id).then(() => { if (active?.id === id) newResearch(); setDeleteCandidate(null); setHistoryOpen(true) }).catch(() => setHistoryActionError(t('research.deleteResearchError')))
        }}>{t('research.deleteResearchTitle')}</Button>}>
        <p>{t('research.deleteResearchHint', { name: deleteCandidate?.title ?? '' })}</p>
        {historyActionError && <InlineAlert tone="danger">{historyActionError}</InlineAlert>}
      </Modal>
      <Modal open={contextOpen} onClose={() => setContextOpen(false)} title={t('research.context')} maxWidth={640}
        footer={<Button variant="primary" onClick={() => setContextOpen(false)}>{t('research.doneSelecting')}</Button>}>
        <p className="research-muted">{t('research.contextHint')}</p>
        <Tabs
          items={[
            { key: 'documents', label: t('research.contextDocuments'), badge: selected.length },
            { key: 'molecules', label: t('research.contextMolecules'), badge: moleculeRefs.length },
            { key: 'tasks', label: t('research.contextTasks'), badge: taskRefs.length },
          ]}
          activeKey={contextTab}
          onChange={key => setContextTab(key as typeof contextTab)}
          variant="segment"
          size="sm"
          fullWidth
          className="research-context-tabs"
        />
        {contextTab === 'documents' && <>
          <Input value={documentSearch} onChange={event => setDocumentSearch(event.target.value)} placeholder={t('research.searchDocuments')} ariaLabel={t('research.searchDocuments')} />
          {docs.isPending ? <p>{t('research.loading')}</p> : docs.isError ? <InlineAlert tone="danger">{t('research.documentsError')} <Button onClick={() => void docs.refetch()}>{t('research.retry')}</Button></InlineAlert>
            : <div className="research-document-picker">{documents.filter(doc => (doc.title + ' ' + doc.file_name).toLowerCase().includes(documentSearch.toLowerCase())).map(doc => (
              <Chip key={doc.doc_id} label={doc.title || doc.file_name} active={researchDocumentIds.includes(doc.doc_id)}
                disabled={busy || (!researchDocumentIds.includes(doc.doc_id) && researchDocumentIds.length >= 8)}
                onClick={() => setResearchDocumentIds(ids => ids.includes(doc.doc_id) ? ids.filter(id => id !== doc.doc_id) : [...ids, doc.doc_id])} />
            ))}{documents.length === 0 && <p>{t('research.noDocuments')}</p>}</div>}
        </>}
        {contextTab === 'molecules' && <>
          <Input value={moleculeSearch} onChange={event => setMoleculeSearch(event.target.value)} placeholder={t('research.searchMolecules')} ariaLabel={t('research.searchMolecules')} />
          {moleculePage.isPending ? <p>{t('research.loading')}</p> : moleculePage.isError ? <InlineAlert tone="danger">{t('research.moleculesError')} <Button onClick={() => void moleculePage.refetch()}>{t('research.retry')}</Button></InlineAlert>
            : <div className="research-document-picker">{moleculePage.data.items.map(molecule => {
              const included = moleculeRefs.some(reference => reference.mol_id === molecule.mol_id)
              return <Chip key={molecule.mol_id} label={`${molecule.name || molecule.mol_id} · ${molecule.mol_id}`}
                active={included} disabled={busy || (!included && moleculeRefs.length >= 8)}
                onClick={() => setMoleculeRefs(refs => included
                  ? refs.filter(reference => reference.mol_id !== molecule.mol_id)
                  : [...refs, { mol_id: molecule.mol_id, name: (molecule.name || molecule.mol_id).slice(0, 160) }])} />
            })}{moleculePage.data.items.length === 0 && <p>{t('research.noMolecules')}</p>}</div>}
        </>}
        {contextTab === 'tasks' && <>
          <Input value={taskSearch} onChange={event => setTaskSearch(event.target.value)} placeholder={t('research.searchTasks')} ariaLabel={t('research.searchTasks')} />
          {queue.isPending ? <p>{t('research.loading')}</p> : queue.isError ? <InlineAlert tone="danger">{t('research.tasksError')} <Button onClick={() => void queue.refetch()}>{t('research.retry')}</Button></InlineAlert>
            : <div className="research-document-picker">{queue.data.filter(task => {
              const doc = documents.find(item => item.doc_id === task.doc_id)
              return `${doc?.title ?? ''} ${doc?.file_name ?? ''} ${task.file_path} ${task.run_id}`.toLowerCase().includes(taskSearch.toLowerCase())
            }).sort((a, b) => b.updated_at - a.updated_at).slice(0, 50).map(task => {
              const included = taskRefs.some(reference => reference.task_id === task.id)
              const doc = documents.find(item => item.doc_id === task.doc_id)
              const label = `${doc?.title || doc?.file_name || task.file_path.split(/[\\/]/).pop()} · ${t('pdfPipeline.stage.' + task.stage)} · ${t('research.task.' + task.status)} · ${task.run_id.slice(0, 8)}`
              return <Chip key={task.id} label={label} active={included}
                disabled={busy || (!included && taskRefs.length >= 8)}
                onClick={() => setTaskRefs(refs => included
                  ? refs.filter(reference => reference.task_id !== task.id)
                  : [...refs, { task_id: task.id, run_id: task.run_id, doc_id: task.doc_id, stage: task.stage, status: task.status }])} />
            })}{queue.data.length === 0 && <p>{t('research.noTasks')}</p>}</div>}
        </>}
      </Modal>
    </section>
  )
}
