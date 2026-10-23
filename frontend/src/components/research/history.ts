export interface ResearchMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  status?: 'complete' | 'stopped' | 'failed'
}

export interface ResearchMoleculeReference {
  mol_id: string
  name: string
}

export interface ResearchTaskReference {
  task_id: string
  run_id: string
  doc_id: string
  stage?: string
  status?: string
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

export const historyKey = (libraryRoot: string) => `mbforge.research.v1:${libraryRoot}`

export function readHistory(libraryRoot: string): ResearchSession[] {
  try {
    const raw = localStorage.getItem(historyKey(libraryRoot))
    if (!raw || raw.length > 4_000_000) return []
    const value: unknown = JSON.parse(raw)
    if (!Array.isArray(value)) return []
    return value.filter((session): session is ResearchSession => {
      if (!session || typeof session !== 'object') return false
      const item = session as Record<string, unknown>
      return typeof item.id === 'string' && typeof item.title === 'string'
        && typeof item.updatedAt === 'number' && Number.isFinite(item.updatedAt)
        && Array.isArray(item.messages) && item.messages.length <= 200
        && (item.documentIds === undefined || (Array.isArray(item.documentIds) && item.documentIds.length <= 8
          && item.documentIds.every(id => typeof id === 'string')))
        && (item.moleculeRefs === undefined || (Array.isArray(item.moleculeRefs) && item.moleculeRefs.length <= 8
          && item.moleculeRefs.every((ref: unknown) => {
            if (!ref || typeof ref !== 'object') return false
            const molecule = ref as Record<string, unknown>
            return typeof molecule.mol_id === 'string' && molecule.mol_id.length <= 128
              && typeof molecule.name === 'string' && molecule.name.length <= 160
          })))
        && (item.taskRefs === undefined || (Array.isArray(item.taskRefs) && item.taskRefs.length <= 8
          && item.taskRefs.every((ref: unknown) => {
            if (!ref || typeof ref !== 'object') return false
            const task = ref as Record<string, unknown>
            return typeof task.task_id === 'string' && task.task_id.length <= 128
              && typeof task.run_id === 'string' && task.run_id.length <= 128
              && typeof task.doc_id === 'string' && task.doc_id.length <= 128
          })))
        && item.messages.every((message: unknown) => {
          if (!message || typeof message !== 'object') return false
          const m = message as Record<string, unknown>
          return typeof m.id === 'string' && (m.role === 'user' || m.role === 'assistant')
            && typeof m.content === 'string'
            && (m.status === undefined || (typeof m.status === 'string' && ['complete', 'stopped', 'failed'].includes(m.status)))
        })
    }).slice(0, 20).map(session => ({
      ...session,
      moleculeRefs: session.moleculeRefs?.map(({ mol_id, name }) => ({ mol_id, name: name.slice(0, 160) })),
      taskRefs: session.taskRefs?.map(({ task_id, run_id, doc_id }) => ({ task_id, run_id, doc_id })),
      messages: session.messages.map(message =>
        message.role === 'assistant' && message.status === undefined ? { ...message, status: 'stopped' as const } : message),
    }))
  } catch {
    return []
  }
}
