/** React Query hooks for document artifacts and page-scoped SQL evidence. */

import { useQuery } from '@tanstack/react-query'
import {
  fetchDocumentEvidence,
  fetchDocumentMarkdown,
  fetchPatentFacts,
} from '../../http/library'
import { queryKeys } from '../keys'

/**
 * A document's extracted markdown, shared between the standalone
 * MarkdownViewer and the workspace MarkdownPane so a doc opened in
 * both places only fetches once and stays fresh across views.
 *
 * ``fetchDocumentMarkdown`` swallows HTTP errors into ``{ok:false,error}``,
 * so the query resolves successfully either way; consumers read ``data.ok``.
 */
export function useDocumentMarkdown(docId: string | null, libraryRoot: string | null) {
  return useQuery({
    queryKey: queryKeys.documents.markdown(docId ?? '', libraryRoot ?? ''),
    queryFn: () => fetchDocumentMarkdown(docId as string, libraryRoot as string),
    enabled: Boolean(docId) && Boolean(libraryRoot),
  })
}

export function useDocumentPatentFacts(docId: string | null, libraryRoot: string | null) {
  return useQuery({
    queryKey: queryKeys.documents.patentFacts(docId ?? '', libraryRoot ?? ''),
    queryFn: () => fetchPatentFacts(docId as string, libraryRoot as string),
    enabled: Boolean(docId) && Boolean(libraryRoot),
  })
}

export function useDocumentEvidence(
  docId: string | null,
  page: number,
  libraryRoot: string | null,
) {
  return useQuery({
    queryKey: queryKeys.documents.evidence(docId ?? '', page, libraryRoot ?? ''),
    queryFn: () => fetchDocumentEvidence(docId as string, page, libraryRoot as string),
    enabled: Boolean(docId) && Boolean(libraryRoot) && page > 0,
  })
}
