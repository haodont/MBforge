/** Model-facing contract of the scientific search tools: searchStructures, searchPapers. */
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { searchPapers, searchStructures } from './scientific.js'

test('structure and literature searches return traceable metadata, capped records and canonical links', async t => {
  const originalFetch = globalThis.fetch
  const requested: string[] = []
  let papersUrl = ''
  t.after(() => { globalThis.fetch = originalFetch })
  globalThis.fetch = (async (input, init) => {
    const url = String(input)
    requested.push(url)
    if (url.endsWith('/rcsbsearch/v2/query')) {
      const body = JSON.parse(String(init?.body)) as { return_type: string; request_options: { paginate: { rows: number } } }
      assert.equal(body.return_type, 'entry')
      assert.equal(body.request_options.paginate.rows, 1)
      return Response.json({ result_set: [{ identifier: '7S8N' }, { identifier: '9WVX' }] })
    }
    if (url.endsWith('/core/entry/7S8N')) return Response.json({
      struct: { title: 'MRGPRX2 antagonist complex' },
      exptl: [{ method: 'ELECTRON MICROSCOPY' }],
      rcsb_entry_info: { resolution_combined: [3.42] },
      rcsb_entry_container_identifiers: { polymer_entity_ids: ['1'], non_polymer_entity_ids: ['2'], emdb_ids: ['EMD-1234'] },
      rcsb_primary_citation: { title: 'A structure paper', pdbx_database_id_DOI: '10.1000/example', pdbx_database_id_PubMed: '12345' },
    })
    if (url.endsWith('/core/polymer_entity/7S8N/1')) return Response.json({
      entity_poly: { pdbx_description: 'Human MRGPRX2', pdbx_strand_id: 'A' },
      rcsb_entity_source_organism: [{ ncbi_scientific_name: 'Homo sapiens' }],
    })
    if (url.endsWith('/core/nonpolymer_entity/7S8N/2')) return Response.json({
      nonpolymer_comp: {
        chem_comp: { id: 'E23', name: 'Example antagonist' },
        rcsb_chem_comp_descriptor: { InChIKey: 'AAAAAAAAAAAAAA-BBBBBBBBBB-C' },
      },
    })
    if (url.startsWith('https://www.ebi.ac.uk/europepmc/webservices/rest/search?')) {
      papersUrl = url
      return Response.json({
        hitCount: 12,
        resultList: { result: [
          { title: 'First paper', authorString: 'A Author', journalInfo: { yearOfPublication: 2026, journal: { title: 'Journal' } }, doi: '10.1000/first', pmid: '12345', pmcid: 'PMC123', isOpenAccess: 'Y', abstractText: 'Abstract text' },
          { title: 'Second paper', pmid: '23456' },
        ] },
      })
    }
    return new Response('not found', { status: 404 })
  }) as typeof fetch

  const structures = await searchStructures('MRGPRX2', 1)
  assert.equal(structures.results.length, 1)
  assert.equal(structures.results[0].pdb_id, '7S8N')
  assert.equal(structures.results[0].experimental_methods[0], 'ELECTRON MICROSCOPY')
  assert.equal(structures.results[0].resolution_angstrom, 3.42)
  assert.deepEqual(structures.results[0].organisms, ['Homo sapiens'])
  assert.equal(structures.results[0].publication.url, 'https://doi.org/10.1000/example')
  assert.deepEqual(structures.results[0].nonpolymer_components[0], {
    component_id: 'E23', name: 'Example antagonist', inchi_key: 'AAAAAAAAAAAAAA-BBBBBBBBBB-C',
  })
  assert.equal(structures.results[0].download_mmcif_url, 'https://files.rcsb.org/download/7S8N.cif')
  assert.ok(requested.every(url => url.startsWith('https://search.rcsb.org/') || url.startsWith('https://data.rcsb.org/')))
  assert.ok(!requested.some(url => url.endsWith('/core/entry/9WVX')))

  const papers = await searchPapers('MRGPRX2 structure', 1)
  assert.ok(papersUrl.startsWith('https://www.ebi.ac.uk/europepmc/webservices/rest/search?'))
  assert.match(papersUrl, /pageSize=1/)
  assert.equal(papers.result_count, 12)
  assert.equal(papers.results.length, 1)
  assert.equal(papers.results[0].source_url, 'https://europepmc.org/article/PMC/PMC123')
  assert.equal(papers.results[0].year, '2026')
  assert.equal(papers.results[0].doi, '10.1000/first')
  assert.equal(papers.results[0].abstract, 'Abstract text')
})
