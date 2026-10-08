/** Query key factory — centralised, typed, and collocation-friendly.
 *
 *  Usage:
 *    queryClient.invalidateQueries({ queryKey: queryKeys.documents.all })
 *    const { data } = useQuery({ queryKey: queryKeys.documents.list(), … })
 */

export const queryKeys = {
  library: {
    all: ['library'] as const,
    status: () => [...queryKeys.library.all, 'status'] as const,
  },

  documents: {
    all: ['documents'] as const,
    list: () => [...queryKeys.documents.all, 'list'] as const,
    markdown: (docId: string, libraryRoot: string) =>
      [...queryKeys.documents.all, 'markdown', docId, libraryRoot] as const,
    patentFacts: (docId: string, libraryRoot: string) =>
      [...queryKeys.documents.all, 'patent-facts', docId, libraryRoot] as const,
    evidence: (docId: string, page: number, libraryRoot: string) =>
      [...queryKeys.documents.all, 'evidence', docId, page, libraryRoot] as const,
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

  pdf: {
    all: ['pdf'] as const,
    overlay: (libraryRoot: string, docId: string, path: string) =>
      [...queryKeys.pdf.all, 'overlay', libraryRoot, docId, path] as const,
  },

  molecules: {
    all: ['molecules'] as const,
    list: (libraryRoot: string) =>
      [...queryKeys.molecules.all, 'list', libraryRoot] as const,
    page: (libraryRoot: string, params: unknown) =>
      [...queryKeys.molecules.all, 'page', libraryRoot, params] as const,
    detail: (libraryRoot: string, molId: string) =>
      [...queryKeys.molecules.all, 'detail', libraryRoot, molId] as const,
    stats: (libraryRoot: string) =>
      [...queryKeys.molecules.all, 'stats', libraryRoot] as const,
    corrections: (libraryRoot: string, molId: string) =>
      [...queryKeys.molecules.all, 'corrections', libraryRoot, molId] as const,
    byLocation: (
      libraryRoot: string,
      docId: string,
      page: number,
      bbox: [number, number, number, number] | null,
    ) =>
      [...queryKeys.molecules.all, 'by-location', libraryRoot, docId, page, bbox] as const,
    descriptors: (smiles: string) =>
      [...queryKeys.molecules.all, 'descriptors', smiles] as const,
    validation: (smiles: string) =>
      [...queryKeys.molecules.all, 'validation', smiles] as const,
    svg: (smiles: string, width: number, height: number) =>
      [...queryKeys.molecules.all, 'svg', smiles, width, height] as const,
    clusters: () => [...queryKeys.molecules.all, 'clusters'] as const,
    clusterMembers: (clusterId: string) =>
      [...queryKeys.molecules.all, 'cluster-members', clusterId] as const,
    relationStats: () => [...queryKeys.molecules.all, 'relation-stats'] as const,
    relations: (molId: string) =>
      [...queryKeys.molecules.all, 'relations', molId] as const,
    substructure: (query: string, threshold: number) =>
      [...queryKeys.molecules.all, 'substructure', query, threshold] as const,
    analogs: (molId: string, minSimilarity: number) =>
      [...queryKeys.molecules.all, 'analogs', molId, minSimilarity] as const,
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
    configDir: () => [...queryKeys.settings.all, 'config-dir'] as const,
    llmEnv: () => [...queryKeys.settings.all, 'llm-env'] as const,
  },

  about: {
    all: ['about'] as const,
    buildInfo: () => [...queryKeys.about.all, 'build-info'] as const,
  },

  sidecar: {
    all: ['sidecar'] as const,
    status: () => [...queryKeys.sidecar.all, 'status'] as const,
  },

  dirs: {
    all: ['dirs'] as const,
    common: () => [...queryKeys.dirs.all, 'common'] as const,
  },

  models: {
    all: ['models'] as const,
    list: () => [...queryKeys.models.all, 'list'] as const,
    cacheDir: () => [...queryKeys.models.all, 'cache-dir'] as const,
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

  docking: {
    all: ['docking'] as const,
    engine: () => [...queryKeys.docking.all, 'engine'] as const,
    receptors: () => [...queryKeys.docking.all, 'receptors'] as const,
    jobs: (status: string) => [...queryKeys.docking.all, 'jobs', status] as const,
    job: (jobId: string) => [...queryKeys.docking.all, 'job', jobId] as const,
  },

  sar: {
    all: ['sar'] as const,
    cliffs: (libraryRoot: string, minSimilarity: number, minActivityRatio: number) =>
      [...queryKeys.sar.all, 'cliffs', libraryRoot, minSimilarity, minActivityRatio] as const,
    scaffoldProfile: (libraryRoot: string, scaffoldEsmiles: string) =>
      [...queryKeys.sar.all, 'scaffold-profile', libraryRoot, scaffoldEsmiles] as const,
    matrix: (compounds: readonly unknown[], coreSmiles: string) =>
      [...queryKeys.sar.all, 'matrix', compounds, coreSmiles] as const,
    heatmap: (matrix: unknown, lowerIsBetter: boolean) =>
      [...queryKeys.sar.all, 'heatmap', matrix, lowerIsBetter] as const,
  },
} as const
