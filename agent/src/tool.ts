import { Type } from '@earendil-works/pi-ai'
import { defineTool } from '@earendil-works/pi-coding-agent'

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
export async function postTool<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${backendBaseUrl()}${path}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    })
  } catch (error) {
    // A callback that never reaches the backend used to fail in silence: the model
    // simply retried until its budget ran out, with nothing in any log to say why.
    console.error(`[mbforge] ${path} unreachable at ${backendBaseUrl()}:`, error)
    throw error
  }
  if (!response.ok) {
    const detail = (await response.text()).slice(0, 400)
    console.error(`[mbforge] ${path} failed (${response.status}): ${detail}`)
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

export const searchLibraryParameters = Type.Object({
  query: Type.String({ minLength: 1, maxLength: 400, description: '1-10 literal keywords; all must occur in the same evidence row, case-insensitive.' }),
  doc_id: Type.Optional(Type.String({ maxLength: 128 })),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 50 })),
  offset: Type.Optional(Type.Integer({ minimum: 0, maximum: 10000 })),
}, { additionalProperties: false })

export const searchLibraryTool = defineTool({
  name: 'search_library', label: 'Search library text',
  description: 'Search extracted SQL source text across documents, optionally within one doc_id. Returns bounded snippets with document, page, evidence ID and pagination. Empty results do not prove absence.',
  parameters: searchLibraryParameters,
  async execute(_id, params, signal) {
    return toolResult('search_library', await postTool('/api/v1/agent/tools/search-library', params, signal), {})
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
