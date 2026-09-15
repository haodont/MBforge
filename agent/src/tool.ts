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
    const response = await fetch(`${backendBaseUrl()}/api/v1/agent/tools/molecule-search`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ query: params.query, mode: params.mode ?? 'auto' }),
      signal,
    })

    if (!response.ok) {
      const detail = (await response.text()).slice(0, 400)
      throw new Error(`MBForge molecule search failed (${response.status}): ${detail}`)
    }

    const payload = (await response.json()) as Partial<MoleculeSearchResponse>
    if (!payload.success || !Array.isArray(payload.results)) {
      throw new Error('MBForge molecule search returned an invalid tool response')
    }

    return {
      content: [{ type: 'text', text: JSON.stringify(payload.results) }],
      details: {
        tool: 'molecule_search' as const,
        results: payload.results,
      },
    }
  },
})
