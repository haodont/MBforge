import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createResearchSession, deleteResearchSession, getResearchSession, importResearchSession, listResearchSessions } from '@/api/http/research'
import type { ResearchSession } from '@/api/http/research'
import { queryKeys } from '../keys'

const indexKey = queryKeys.research.sessions
const detailKey = queryKeys.research.session

export function useResearchSessions(root: string) {
  return useQuery({ queryKey: indexKey(root), queryFn: () => listResearchSessions(root), enabled: Boolean(root) })
}
export function useResearchSession(root: string, id: string | null) {
  return useQuery({ queryKey: detailKey(root, id ?? ''), queryFn: () => getResearchSession(root, id ?? ''), enabled: Boolean(root && id),
    refetchInterval: query => query.state.data?.messages.some(message => message.status === 'pending') ? 2000 : false })
}
export function useCreateResearchSession(root: string) {
  const client = useQueryClient()
  return useMutation({ mutationFn: (title: string) => createResearchSession(root, title), onSuccess: () => { void client.invalidateQueries({ queryKey: indexKey(root) }) } })
}
export function useLoadResearchSession(root: string) {
  const client = useQueryClient()
  return useMutation({ mutationFn: (id: string) => getResearchSession(root, id), onSuccess: session => {
    client.setQueryData(detailKey(root, session.id), session)
  } })
}
export function useImportResearchHistory(root: string) {
  const client = useQueryClient()
  return useMutation({ mutationFn: async (sessions: ResearchSession[]) => {
    for (const session of sessions) await importResearchSession(root, session)
  }, onSuccess: () => { void client.invalidateQueries({ queryKey: indexKey(root) }) } })
}
export function useDeleteResearchSession(root: string) {
  const client = useQueryClient()
  return useMutation({ mutationFn: (id: string) => deleteResearchSession(root, id), onSuccess: (_data, id) => {
    client.removeQueries({ queryKey: detailKey(root, id) })
    void client.invalidateQueries({ queryKey: indexKey(root) })
  } })
}
