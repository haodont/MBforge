/** Query key factory — centralised, typed, and collocation-friendly.
 *
 *  Usage:
 *    queryClient.invalidateQueries({ queryKey: queryKeys.documents.all })
 *    const { data } = useQuery({ queryKey: queryKeys.documents.list(collectionId), … })
 */

export const queryKeys = {
  library: {
    all: ['library'] as const,
    status: () => [...queryKeys.library.all, 'status'] as const,
  },

  documents: {
    all: ['documents'] as const,
    list: (collectionId?: string) =>
      [...queryKeys.documents.all, { collectionId }] as const,
    markdown: (docId: string, libraryRoot: string) =>
      [...queryKeys.documents.all, 'markdown', docId, libraryRoot] as const,
    patentFacts: (docId: string, libraryRoot: string) =>
      [...queryKeys.documents.all, 'patent-facts', docId, libraryRoot] as const,
    evidence: (docId: string, page: number, libraryRoot: string) =>
      [...queryKeys.documents.all, 'evidence', docId, page, libraryRoot] as const,
  },

  collections: {
    all: ['collections'] as const,
    list: () => [...queryKeys.collections.all, 'list'] as const,
  },

  ingest: {
    all: ['ingest'] as const,
    queue: (libraryRoot: string) =>
      [...queryKeys.ingest.all, 'queue', libraryRoot] as const,
    stats: (libraryRoot: string) =>
      [...queryKeys.ingest.all, 'stats', libraryRoot] as const,
    logs: (libraryRoot: string, docId: string) =>
      [...queryKeys.ingest.all, 'logs', libraryRoot, docId] as const,
    workerStatus: () =>
      [...queryKeys.ingest.all, 'worker-status'] as const,
  },

  molecules: {
    all: ['molecules'] as const,
    list: (libraryRoot: string) =>
      [...queryKeys.molecules.all, 'list', libraryRoot] as const,
    stats: (libraryRoot: string) =>
      [...queryKeys.molecules.all, 'stats', libraryRoot] as const,
  },

  markush: {
    all: ['markush'] as const,
    list: (libraryRoot: string, params: Record<string, unknown> = {}) =>
      [...queryKeys.markush.all, 'list', libraryRoot, params] as const,
    detail: (libraryRoot: string, candidateId: string) =>
      [...queryKeys.markush.all, 'detail', libraryRoot, candidateId] as const,
  },

  notes: {
    all: ['notes'] as const,
    list: (libraryRoot: string) =>
      [...queryKeys.notes.all, libraryRoot] as const,
    backlinks: (libraryRoot: string, targetId: string) =>
      [...queryKeys.notes.all, 'backlinks', libraryRoot, targetId] as const,
  },

  settings: {
    all: ['settings'] as const,
    get: () => [...queryKeys.settings.all, 'get'] as const,
  },

  docs: {
    all: ['docs'] as const,
    index: () => [...queryKeys.docs.all, 'index'] as const,
    page: (slug: string) => [...queryKeys.docs.all, 'page', slug] as const,
  },

  readiness: {
    all: ['readiness'] as const,
    summary: () => [...queryKeys.readiness.all, 'summary'] as const,
  },

  review: {
    all: ['review'] as const,
    queue: (
      libraryRoot: string,
      filters: { kind?: string; status?: string; docId?: string; page?: number; pageSize?: number },
    ) => [...queryKeys.review.all, 'queue', libraryRoot, filters] as const,
    stats: (libraryRoot: string) =>
      [...queryKeys.review.all, 'stats', libraryRoot] as const,
    history: (libraryRoot: string, entityId: string) =>
      [...queryKeys.review.all, 'history', libraryRoot, entityId] as const,
  },
} as const
