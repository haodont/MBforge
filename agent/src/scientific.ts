import { Type } from 'typebox'
import { defineTool } from '@earendil-works/pi-coding-agent'

const RCSB_SEARCH = 'https://search.rcsb.org/rcsbsearch/v2/query'
const RCSB_DATA = 'https://data.rcsb.org/rest/v1/core'
const EUROPE_PMC = 'https://www.ebi.ac.uk/europepmc/webservices/rest'

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function string(value: unknown): string {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : ''
}

function boundedQuery(query: string): string {
  const value = query.trim()
  if (!value || value.length > 200) throw new Error('Search query must contain 1 to 200 characters')
  return value
}

function resultLimit(value: number, maximum: number): number {
  return Number.isFinite(value) ? Math.min(maximum, Math.max(1, Math.floor(value))) : maximum
}

async function getJson(url: string, signal?: AbortSignal): Promise<Record<string, unknown>> {
  const timeout = AbortSignal.timeout(15000)
  const requestSignal = signal ? AbortSignal.any([signal, timeout]) : timeout
  const response = await fetch(url, { headers: { accept: 'application/json' }, signal: requestSignal })
  if (!response.ok) throw new Error(`Scientific database request failed (HTTP ${response.status})`)
  return record(await response.json())
}

function textResult(payload: unknown) {
  return { content: [{ type: 'text' as const, text: JSON.stringify(payload) }], details: {} }
}

export async function searchStructures(query: string, maxResults = 3, signal?: AbortSignal) {
  const term = boundedQuery(query)
  const limit = resultLimit(maxResults, 3)
  const timeout = AbortSignal.timeout(15000)
  const requestSignal = signal ? AbortSignal.any([signal, timeout]) : timeout
  const response = await fetch(RCSB_SEARCH, {
    method: 'POST',
    headers: { accept: 'application/json', 'content-type': 'application/json' },
    signal: requestSignal,
    body: JSON.stringify({
      query: { type: 'terminal', service: 'full_text', parameters: { value: term } },
      return_type: 'entry',
      request_options: { paginate: { start: 0, rows: limit } },
    }),
  })
  if (!response.ok) throw new Error(`RCSB PDB search failed (HTTP ${response.status})`)
  const search = record(await response.json())
  const ids = [...new Set(list(search.result_set)
    .map(item => string(record(item).identifier).toUpperCase())
    .filter(id => /^[A-Z0-9]{4}$/.test(id)))].slice(0, limit)

  const results = await Promise.all(ids.map(async pdbId => {
    const entry = await getJson(`${RCSB_DATA}/entry/${pdbId}`, signal)
    const identifiers = record(entry.rcsb_entry_container_identifiers)
    const polymerIds = list(identifiers.polymer_entity_ids).map(string).filter(Boolean).slice(0, 2)
    const componentIds = list(identifiers.non_polymer_entity_ids).map(string).filter(Boolean).slice(0, 8)
    const [polymers, components] = await Promise.all([
      Promise.allSettled(polymerIds.map(id => getJson(`${RCSB_DATA}/polymer_entity/${pdbId}/${encodeURIComponent(id)}`, signal))),
      Promise.allSettled(componentIds.map(id => getJson(`${RCSB_DATA}/nonpolymer_entity/${pdbId}/${encodeURIComponent(id)}`, signal))),
    ])
    if (signal?.aborted) throw new Error('Structure search aborted')
    const polymerEntities = polymers.flatMap(item => item.status === 'fulfilled' ? [item.value] : [])
    const nonpolymerEntities = components.flatMap(item => item.status === 'fulfilled' ? [item.value] : [])
    const organisms = polymerEntities.flatMap(item => list(item.rcsb_entity_source_organism).map(value => string(record(value).ncbi_scientific_name)).filter(Boolean))
    const targetEntities = polymerEntities.map(item => ({
      description: string(record(item.entity_poly).pdbx_description),
      chains: string(record(item.entity_poly).pdbx_strand_id),
      organisms: list(item.rcsb_entity_source_organism).map(value => string(record(value).ncbi_scientific_name)).filter(Boolean),
    }))
    const ligands = nonpolymerEntities.map(item => {
      const component = record(item.nonpolymer_comp)
      const chemical = record(component.chem_comp)
      const descriptorValue = component.rcsb_chem_comp_descriptor
      const descriptor = Array.isArray(descriptorValue) ? record(descriptorValue[0]) : record(descriptorValue)
      return {
        component_id: string(chemical.id),
        name: string(chemical.name),
        inchi_key: string(descriptor.InChIKey),
      }
    }).filter(item => item.component_id || item.name)
    const citation = record(entry.rcsb_primary_citation)
    const info = record(entry.rcsb_entry_info)
    const experimentalMethods = list(entry.exptl).map(item => string(record(item).method)).filter(Boolean)
    const emdbIds = list(identifiers.emdb_ids).map(string).filter(id => /^EMD-\d+$/i.test(id))
    const resolution = list(info.resolution_combined).map(Number).filter(Number.isFinite)
    const doi = string(citation.pdbx_database_id_DOI)
    const pmid = string(citation.pdbx_database_id_PubMed)
    const failedEntityReads = polymers.length - polymerEntities.length + components.length - nonpolymerEntities.length > 0

    return {
      pdb_id: pdbId,
      title: string(record(entry.struct).title),
      experimental_methods: experimentalMethods,
      resolution_angstrom: resolution[0] ?? null,
      organisms: [...new Set(organisms)],
      target_entities: targetEntities,
      nonpolymer_components: ligands,
      components_truncated: list(identifiers.non_polymer_entity_ids).length > componentIds.length,
      emdb_ids: emdbIds,
      publication: {
        title: string(citation.title),
        doi,
        pmid,
        url: /^10\.\d{4,9}\/\S+$/i.test(doi) ? `https://doi.org/${doi}`
          : /^\d+$/.test(pmid) ? `https://pubmed.ncbi.nlm.nih.gov/${pmid}/` : '',
      },
      rcsb_url: `https://www.rcsb.org/structure/${pdbId}`,
      download_pdb_url: `https://files.rcsb.org/download/${pdbId}.pdb`,
      download_mmcif_url: `https://files.rcsb.org/download/${pdbId}.cif`,
      emdb_urls: emdbIds.map(id => `https://www.ebi.ac.uk/emdb/${id}`),
      metadata_partial: failedEntityReads,
    }
  }))

  return {
    source: 'RCSB Protein Data Bank',
    query: term,
    retrieved_at: new Date().toISOString(),
    results,
    note: 'A component code or name alone does not establish chemical identity. Compare an exact InChIKey or structure before claiming a bound ligand match; a structure hit does not prove binding to the queried target.',
  }
}

export async function searchPapers(query: string, maxResults = 5, signal?: AbortSignal) {
  const term = boundedQuery(query)
  const limit = resultLimit(maxResults, 5)
  const url = `${EUROPE_PMC}/search?query=${encodeURIComponent(term)}&format=json&pageSize=${limit}&resultType=core`
  const response = await getJson(url, signal)
  const searchResult = record(response.resultList)
  const results = list(searchResult.result).slice(0, limit).map(value => {
    const row = record(value)
    const journalInfo = record(row.journalInfo)
    const journal = record(journalInfo.journal)
    const pmid = string(row.pmid)
    const pmcid = string(row.pmcid)
    const doi = string(row.doi)
    const url = /^PMC\d+$/i.test(pmcid)
      ? `https://europepmc.org/article/PMC/${pmcid}`
      : pmid ? `https://europepmc.org/article/MED/${pmid}`
        : /^10\.\d{4,9}\/\S+$/i.test(doi) ? `https://doi.org/${doi}` : ''
    return {
      title: string(row.title),
      authors: string(row.authorString),
      journal: string(journal.title),
      year: string(journalInfo.yearOfPublication || row.firstPublicationDate || row.pubYear),
      doi,
      pmid,
      pmcid,
      is_open_access: string(row.isOpenAccess).toUpperCase() === 'Y',
      abstract: string(row.abstractText).slice(0, 1800),
      source_url: url,
    }
  })
  return {
    source: 'Europe PMC',
    query: term,
    retrieved_at: new Date().toISOString(),
    result_count: Number(response.hitCount) || 0,
    results,
  }
}

export function createScientificSearchTools() {
  return [
    defineTool({
      name: 'search_structures',
      label: 'Search experimental structures',
      description: 'Search deposited experimental macromolecular structures in the RCSB PDB. Returns species, method, resolution, non-polymer component IDs/InChIKeys, related citation and direct PDB/mmCIF downloads. A hit is not proof that a named ligand is chemically identical or bound to the target.',
      parameters: Type.Object({
        query: Type.String({ minLength: 1, maxLength: 200 }),
        max_results: Type.Optional(Type.Integer({ minimum: 1, maximum: 3 })),
      }, { additionalProperties: false }),
      async execute(_id, params, signal) {
        return textResult(await searchStructures(params.query, params.max_results, signal))
      },
    }),
    defineTool({
      name: 'search_papers',
      label: 'Search biomedical literature',
      description: 'Search Europe PMC records and abstracts for biomedical papers and preprints. Returns verified citation identifiers and source URLs; use web_fetch for accessible full text.',
      parameters: Type.Object({
        query: Type.String({ minLength: 1, maxLength: 200 }),
        max_results: Type.Optional(Type.Integer({ minimum: 1, maximum: 5 })),
      }, { additionalProperties: false }),
      async execute(_id, params, signal) {
        return textResult(await searchPapers(params.query, params.max_results, signal))
      },
    }),
  ]
}
