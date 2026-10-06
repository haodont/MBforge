import { Type } from '@mariozechner/pi-ai'
import { defineTool } from '@mariozechner/pi-coding-agent'

export interface MoleculeSearchResult {
  [key: string]: unknown
}

export interface MoleculeSearchResponse {
  success: boolean
  tool: 'molecule_search'
  results: MoleculeSearchResult[]
}

const backendBaseUrl = (): string => {
  const host = process.env.MBFORGE_BACKEND_HOST ?? '127.0.0.1'
  const port = process.env.MBFORGE_BACKEND_PORT ?? '18792'
  return process.env.MBFORGE_BACKEND_URL ?? `http://${host}:${port}`
}

/** POST a tool request to the backend and parse the JSON reply. HTTP-level
 *  failures throw; a business failure (``success:false``) is returned as data so
 *  the model can read the reason and correct itself. */
async function postTool<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${backendBaseUrl()}${path}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  if (!response.ok) {
    const detail = (await response.text()).slice(0, 400)
    throw new Error(`MBForge tool ${path} failed (${response.status}): ${detail}`)
  }
  return (await response.json()) as T
}

function toolResult(name: string, payload: unknown, details: Record<string, unknown>) {
  return {
    content: [{ type: 'text' as const, text: JSON.stringify(payload) }],
    details: { tool: name, ...details },
  }
}

export const moleculeSearchTool = defineTool({
  name: 'molecule_search',
  label: 'Molecule search',
  description:
    'Search the active MBForge molecule library. Use this before making claims about stored molecules.',
  promptSnippet: 'search the active MBForge molecule library',
  promptGuidelines: [
    'Treat returned molecule fields as source-backed facts, not as a design recommendation.',
    'If no result is returned, say that the active library has no matching record.',
  ],
  parameters: Type.Object({
    query: Type.String({
      minLength: 1,
      maxLength: 512,
      description: 'A molecule name, note, SMILES, or substructure query.',
    }),
    mode: Type.Optional(
      Type.Union([
        Type.Literal('auto'),
        Type.Literal('text'),
        Type.Literal('substructure'),
        Type.Literal('similarity'),
      ]),
    ),
  }),
  async execute(_toolCallId, params, signal) {
    const payload = await postTool<Partial<MoleculeSearchResponse>>(
      '/api/v1/agent/tools/molecule-search',
      { query: params.query, mode: params.mode ?? 'auto' },
      signal,
    )
    if (!payload.success || !Array.isArray(payload.results)) {
      throw new Error('MBForge molecule search returned an invalid tool response')
    }
    return toolResult('molecule_search', payload.results, { results: payload.results })
  },
})

export const libraryStatsTool = defineTool({
  name: 'library_stats',
  label: 'Library statistics',
  description:
    'Return coarse record counts for the active MBForge library: documents (total and by status), molecules, activities, source evidence, Markush review candidates and review items. Use it for overview or "how many" questions.',
  promptSnippet: 'count documents, molecules, activities and other library records',
  promptGuidelines: [
    'Use library_stats for totals and overview questions before drilling into records.',
  ],
  parameters: Type.Object({}),
  async execute(_toolCallId, _params, signal) {
    const payload = await postTool<{ success: boolean; stats: Record<string, unknown> }>(
      '/api/v1/agent/tools/library-stats',
      {},
      signal,
    )
    return toolResult('library_stats', payload.stats ?? {}, { stats: payload.stats })
  },
})

export const queryDocumentsTool = defineTool({
  name: 'query_documents',
  label: 'Query documents',
  description:
    'List or filter the documents in the active MBForge library. Filter by status (pending/extracted/ready/error) and/or a name substring. Returns doc_id, title, file_name, page_count and status.',
  promptSnippet: 'list or filter the library documents',
  promptGuidelines: [
    'Query documents first to obtain a doc_id before querying that document\'s activities or evidence.',
  ],
  parameters: Type.Object({
    status: Type.Optional(
      Type.String({ maxLength: 64, description: 'Optional document status filter.' }),
    ),
    name: Type.Optional(
      Type.String({ maxLength: 256, description: 'Optional title / file-name substring.' }),
    ),
    limit: Type.Optional(Type.Number({ minimum: 1, maximum: 200 })),
  }),
  async execute(_toolCallId, params, signal) {
    const payload = await postTool<{ success: boolean; results: unknown[] }>(
      '/api/v1/agent/tools/query-documents',
      { status: params.status ?? '', name: params.name ?? '', limit: params.limit ?? 50 },
      signal,
    )
    if (!Array.isArray(payload.results)) {
      throw new Error('MBForge query_documents returned an invalid tool response')
    }
    return toolResult('query_documents', payload.results, { results: payload.results })
  },
})

export const queryActivitiesTool = defineTool({
  name: 'query_activities',
  label: 'Query activities',
  description:
    'Return a single document\'s measured bioactivity records (e.g. IC50/EC50/Ki, inhibition %, qualitative ranks) extracted by the Patent stage. Requires the document\'s doc_id; optionally filter by target or assay description.',
  promptSnippet: 'read a document\'s measured activity records',
  promptGuidelines: [
    'Report activity values with their units and target; treat them as source-backed measurements.',
  ],
  parameters: Type.Object({
    doc_id: Type.String({ minLength: 1, maxLength: 256 }),
    target: Type.Optional(Type.String({ maxLength: 256 })),
    assay_description: Type.Optional(Type.String({ maxLength: 256 })),
    limit: Type.Optional(Type.Number({ minimum: 1, maximum: 200 })),
  }),
  async execute(_toolCallId, params, signal) {
    const payload = await postTool<{ success: boolean; results: unknown[] }>(
      '/api/v1/agent/tools/query-activities',
      {
        doc_id: params.doc_id,
        target: params.target ?? '',
        assay_description: params.assay_description ?? '',
        limit: params.limit ?? 50,
      },
      signal,
    )
    if (!Array.isArray(payload.results)) {
      throw new Error('MBForge query_activities returned an invalid tool response')
    }
    return toolResult('query_activities', payload.results, { results: payload.results })
  },
})

export const queryEvidenceTool = defineTool({
  name: 'query_evidence',
  label: 'Query source evidence',
  description:
    'Return a document\'s source-evidence rows (the immutable text/table/molecule regions Extract persisted), optionally filtered by page, kind, or a text substring. Use it to ground a claim in a specific region of the source.',
  promptSnippet: 'read a document\'s source evidence rows',
  promptGuidelines: [
    'Cite the evidence page (and doc_id) when a statement depends on a specific region.',
  ],
  parameters: Type.Object({
    doc_id: Type.String({ minLength: 1, maxLength: 256 }),
    page: Type.Optional(Type.Number({ minimum: 1 })),
    kind: Type.Optional(Type.String({ maxLength: 64 })),
    text: Type.Optional(Type.String({ maxLength: 512 })),
    limit: Type.Optional(Type.Number({ minimum: 1, maximum: 200 })),
  }),
  async execute(_toolCallId, params, signal) {
    const payload = await postTool<{ success: boolean; results: unknown[] }>(
      '/api/v1/agent/tools/query-evidence',
      {
        doc_id: params.doc_id,
        page: params.page,
        kind: params.kind ?? '',
        text: params.text ?? '',
        limit: params.limit ?? 50,
      },
      signal,
    )
    if (!Array.isArray(payload.results)) {
      throw new Error('MBForge query_evidence returned an invalid tool response')
    }
    return toolResult('query_evidence', payload.results, { results: payload.results })
  },
})

export const librarySqlTool = defineTool({
  name: 'library_sql',
  label: 'Library SQL (read-only)',
  description:
    'Run a single read-only SELECT against the library SQLite database, for questions the structured tools do not cover. Call it with an empty sql to get the schema (tables and columns) first. Only SELECT / WITH statements are allowed; writes, PRAGMA, ATTACH and SQLite-internal tables are refused, and results are row-capped.',
  promptSnippet: 'run a read-only SELECT against the library database',
  promptGuidelines: [
    'Call library_sql with an empty sql to discover the schema before writing a query.',
    'Prefer the structured tools (library_stats, query_documents, query_activities, query_evidence) when they answer the question.',
    'Never attempt writes; only SELECT / WITH queries are accepted.',
  ],
  parameters: Type.Object({
    sql: Type.String({
      maxLength: 4000,
      description: 'A single read-only SELECT/WITH statement, or empty to fetch the schema.',
    }),
    max_rows: Type.Optional(Type.Number({ minimum: 1, maximum: 1000 })),
  }),
  async execute(_toolCallId, params, signal) {
    const payload = await postTool<Record<string, unknown>>(
      '/api/v1/agent/tools/library-sql',
      { sql: params.sql, max_rows: params.max_rows ?? 200 },
      signal,
    )
    // Includes both the schema/rows payload and the success:false guard error.
    return toolResult('library_sql', payload, { payload })
  },
})

export const listReceptorsTool = defineTool({
  name: 'list_receptors',
  label: 'List docking receptors',
  description:
    'List the prepared protein receptors available for molecular docking. Returns each receptor_id, name and chain. Use a receptor_id with run_docking.',
  promptSnippet: 'list prepared docking receptors',
  promptGuidelines: [
    'Call list_receptors before run_docking to obtain a valid receptor_id.',
  ],
  parameters: Type.Object({}),
  async execute(_toolCallId, _params, signal) {
    const payload = await postTool<{ success: boolean; items: unknown[] }>(
      '/api/v1/agent/tools/docking-receptors',
      {},
      signal,
    )
    if (!Array.isArray(payload.items)) {
      throw new Error('MBForge list_receptors returned an invalid tool response')
    }
    return toolResult('list_receptors', payload.items, { items: payload.items })
  },
})

export const listDockingJobsTool = defineTool({
  name: 'list_docking_jobs',
  label: 'List docking jobs',
  description:
    'List recent molecular docking jobs with their status (pending/running/done/failed/cancelled). Filter by status if needed.',
  promptSnippet: 'list recent docking jobs',
  promptGuidelines: [
    'Use list_docking_jobs to find a recent job_id, then get_docking_job for its poses.',
  ],
  parameters: Type.Object({
    status: Type.Optional(
      Type.String({ maxLength: 32, description: 'Optional status filter.' }),
    ),
    limit: Type.Optional(Type.Number({ minimum: 1, maximum: 100 })),
  }),
  async execute(_toolCallId, params, signal) {
    const payload = await postTool<{ success: boolean; items: unknown[] }>(
      '/api/v1/agent/tools/docking-jobs',
      { status: params.status ?? '', limit: params.limit ?? 20 },
      signal,
    )
    if (!Array.isArray(payload.items)) {
      throw new Error('MBForge list_docking_jobs returned an invalid tool response')
    }
    return toolResult('list_docking_jobs', payload.items, { items: payload.items })
  },
})

export const getDockingJobTool = defineTool({
  name: 'get_docking_job',
  label: 'Get docking job',
  description:
    'Fetch one docking job by job_id, including its ranked poses (ligand label, affinity in kcal/mol, RMSD). Poll this after run_docking until the status is done or failed.',
  promptSnippet: 'read a docking job and its ranked poses',
  promptGuidelines: [
    'Report pose affinities with units (kcal/mol) and note that more negative is stronger.',
  ],
  parameters: Type.Object({
    job_id: Type.String({ minLength: 1, maxLength: 128 }),
  }),
  async execute(_toolCallId, params, signal) {
    const payload = await postTool<{ success: boolean; job: Record<string, unknown> }>(
      '/api/v1/agent/tools/docking-job',
      { job_id: params.job_id },
      signal,
    )
    return toolResult('get_docking_job', payload.job ?? {}, { job: payload.job })
  },
})

export const runDockingTool = defineTool({
  name: 'run_docking',
  label: 'Run molecular docking',
  description:
    'Queue a molecular docking job: dock the given ligands (SMILES and/or library molecule ids) against a prepared receptor inside a search box (center + size in Ångström). Returns a job_id to poll with get_docking_job. This is expensive — only call it when the user explicitly asks to dock.',
  promptSnippet: 'dock ligands against a receptor',
  promptGuidelines: [
    'Only run docking when the user explicitly asks; it is a heavy GPU job.',
    'Call list_receptors first to get a receptor_id, and never invent one.',
    'Affinities are negative kcal/mol; a more negative value is a stronger predicted binding.',
  ],
  parameters: Type.Object({
    receptor_id: Type.String({ minLength: 1, maxLength: 128 }),
    ligands: Type.Array(
      Type.Object({
        smiles: Type.String({ minLength: 1, maxLength: 2048 }),
        label: Type.Optional(Type.String({ maxLength: 256 })),
        mol_id: Type.Optional(Type.String({ maxLength: 2048 })),
      }),
      { minItems: 1, maxItems: 200 },
    ),
    box: Type.Object({
      center: Type.Array(Type.Number(), { minItems: 3, maxItems: 3 }),
      size: Type.Array(Type.Number(), { minItems: 3, maxItems: 3 }),
    }),
    params: Type.Optional(Type.Record(Type.String(), Type.Unknown())),
  }),
  async execute(_toolCallId, params, signal) {
    const payload = await postTool<{ success: boolean; job: Record<string, unknown> }>(
      '/api/v1/agent/tools/run-docking',
      {
        receptor_id: params.receptor_id,
        ligands: params.ligands,
        box: params.box,
        params: params.params ?? {},
      },
      signal,
    )
    return toolResult('run_docking', payload.job ?? {}, { job: payload.job })
  },
})
