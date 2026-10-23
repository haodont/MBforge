import { apiUrl, httpGet, httpPost, httpFetch } from './_utils'
import { readChatEvents } from './agent'
import type { AgentChatEvent } from './agent'

export interface ResearchMoleculeReference { mol_id: string; name: string }
export interface ResearchTaskReference { task_id: string; run_id: string; doc_id: string; stage?: string; status?: string }
export interface ResearchArtifactReference { doc_id: string; run_id: string; revision: number }
export interface ResearchMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  status?: 'pending' | 'complete' | 'stopped' | 'failed'
  request_id?: string
  taskRefs?: ResearchTaskReference[]
  artifactRefs?: ResearchArtifactReference[]
}
export interface ResearchSession {
  id: string
  title: string
  updatedAt: number
  messages: ResearchMessage[]
  documentIds?: string[]
  moleculeRefs?: ResearchMoleculeReference[]
  taskRefs?: ResearchTaskReference[]
}
export interface ResearchSessionSummary { id: string; title: string; updatedAt: number; messageCount: number }
interface ResearchContext {
  document_ids: string[]
  molecule_refs: ResearchMoleculeReference[]
  task_refs: Array<Pick<ResearchTaskReference, 'task_id' | 'run_id' | 'doc_id'>>
  allow_patent_analysis: boolean
}
interface StoredMessage {
  id: string; request_id: string; role: 'user' | 'assistant'; content: string
  status: 'pending' | 'complete' | 'stopped' | 'failed'
  task_refs: ResearchTaskReference[]; artifact_refs: ResearchArtifactReference[]
}
interface StoredSession {
  id: string; title: string; updated_at: number; revision: number
  context: ResearchContext; messages: StoredMessage[]
}

const context = (session: Pick<ResearchSession, 'documentIds' | 'moleculeRefs' | 'taskRefs'>, allowAnalysis = false): ResearchContext => ({
  document_ids: session.documentIds ?? [], molecule_refs: session.moleculeRefs ?? [],
  task_refs: (session.taskRefs ?? []).map(({ task_id, run_id, doc_id }) => ({ task_id, run_id, doc_id })),
  allow_patent_analysis: allowAnalysis,
})
const fromStored = (session: StoredSession): ResearchSession => ({
  id: session.id, title: session.title, updatedAt: session.updated_at * 1000,
  documentIds: session.context.document_ids, moleculeRefs: session.context.molecule_refs, taskRefs: session.context.task_refs,
  messages: session.messages.map(({ task_refs, artifact_refs, ...message }) => ({ ...message, taskRefs: task_refs, artifactRefs: artifact_refs })),
})
const sessionUrl = (id: string, root: string) => `/api/v1/research/sessions/${encodeURIComponent(id)}?library_root=${encodeURIComponent(root)}`

export async function listResearchSessions(libraryRoot: string): Promise<ResearchSessionSummary[]> {
  const items = await httpGet<Array<{ id: string; title: string; updated_at: number; message_count: number }>>(`/api/v1/research/sessions?library_root=${encodeURIComponent(libraryRoot)}`)
  return items.map(item => ({ id: item.id, title: item.title, updatedAt: item.updated_at * 1000, messageCount: item.message_count }))
}
export async function getResearchSession(libraryRoot: string, id: string): Promise<ResearchSession> {
  return fromStored(await httpGet<StoredSession>(sessionUrl(id, libraryRoot)))
}
export async function createResearchSession(libraryRoot: string, title: string): Promise<ResearchSession> {
  return fromStored(await httpPost<StoredSession>('/api/v1/research/sessions', { library_root: libraryRoot, title }))
}
export async function deleteResearchSession(libraryRoot: string, id: string): Promise<void> {
  await httpFetch(sessionUrl(id, libraryRoot), { method: 'DELETE' })
}
export async function importResearchSession(libraryRoot: string, session: ResearchSession): Promise<void> {
  const messages: StoredMessage[] = []
  for (let index = 0; index < session.messages.length; index++) {
    const user = session.messages[index]
    if (user.role !== 'user') continue
    const next = index + 1 < session.messages.length ? session.messages[index + 1] : undefined
    const assistant = next?.role === 'assistant' ? next : undefined
    const requestId = `import-${session.id}-${index}`
    messages.push({ id: user.id, request_id: requestId, role: 'user', content: user.content, status: 'complete', task_refs: [], artifact_refs: [] },
      { id: assistant?.id ?? `${user.id}-reply`, request_id: requestId, role: 'assistant', content: assistant?.content ?? '', status: assistant?.status === 'complete' ? 'complete' : assistant?.status === 'failed' ? 'failed' : 'stopped', task_refs: [], artifact_refs: [] })
    if (assistant) index++
  }
  await httpPost('/api/v1/research/sessions/import', { library_root: libraryRoot, session: {
    id: session.id, title: session.title, revision: 1, updated_at: session.updatedAt / 1000, context: context(session), messages,
  } })
}
export async function streamResearchChat(
  libraryRoot: string, session: ResearchSession, requestId: string, message: string, allowAnalysis: boolean,
  onEvent: (event: AgentChatEvent) => void, signal: AbortSignal,
): Promise<void> {
  const response = await fetch(apiUrl(`/api/v1/research/sessions/${encodeURIComponent(session.id)}/chat`), {
    method: 'POST', headers: { 'content-type': 'application/json' }, signal,
    body: JSON.stringify({ library_root: libraryRoot, request_id: requestId, message, context: context(session, allowAnalysis) }),
  })
  await readChatEvents(response, onEvent)
}

const validId = (id: unknown): id is string => typeof id === 'string' && /^[a-z0-9_-]{1,128}$/i.test(id)
export function readTaskReference(value: unknown): ResearchTaskReference | null {
  if (!value || typeof value !== 'object') return null
  const ref = value as Record<string, unknown>
  return validId(ref.task_id) && validId(ref.run_id) && validId(ref.doc_id) ? { task_id: ref.task_id, run_id: ref.run_id, doc_id: ref.doc_id } : null
}
export function readArtifactReference(value: unknown): ResearchArtifactReference | null {
  if (!value || typeof value !== 'object') return null
  const ref = value as Record<string, unknown>
  return validId(ref.doc_id) && validId(ref.run_id) && typeof ref.revision === 'number' && Number.isSafeInteger(ref.revision) && ref.revision >= 1
    ? { doc_id: ref.doc_id, run_id: ref.run_id, revision: ref.revision } : null
}
