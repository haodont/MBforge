/**
 * PatentAnalysisPane (src/components/project/pdf/PatentAnalysisPane.tsx):
 * the deterministic Patent result — status/publication badges, the adopted
 * measurement table (assays and species stay separate), extraction notices and
 * the pane's empty state, all read from the committed facts artifact alone.
 */
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import '@/i18n'
import type { PatentFactsArtifact } from '@/api/http/library'
import PatentAnalysisPane from './PatentAnalysisPane'

const methods = ['human MRGPRX2 HEK293', 'mouse Mrgprb2 mast cells'].map((system, index) => ({
  assay_method_id: `assay-${index}`, doc_id: 'doc-1', target: index ? 'Mrgprb2' : 'MRGPRX2', system,
  endpoint: index ? 'degranulation' : 'calcium flux', assay_type: 'IC50', conditions: { species: index ? 'mouse' : 'human' },
  raw_text: system, section_id: '', page_start: index + 1, page_end: index + 1, evidence_ids: [`method-${index}`],
}))

const measurements = methods.map((method, index) => ({
  measurement_id: `measurement-${index}`, doc_id: 'doc-1', compound_entry_id: null, assay_method_id: method.assay_method_id,
  mol_id: 'mol-1', metric: 'IC50', linking_status: 'linked', evidence_ids: [`value-${index}`], provenance: {},
  value: { raw_text: index ? '> 2 µM' : '< 100 nM', operator: index ? '>' : '<', original_value: index ? 2 : 100,
    original_unit: index ? 'µM' : 'nM', canonical_value: null, canonical_unit: '', qualitative_value: '' },
}))

const facts: PatentFactsArtifact = {
  doc_id: 'doc-1',
  run_id: 'run-1',
  revision: 3,
  projection_status: 'current',
  sections: [],
  entries: [],
  synthesis_steps: [],
  assay_methods: methods,
  examples: [],
  measurements,
  issues: [{
    code: 'compound_reference_unresolved',
    severity: 'warning',
    message: 'measurement has no unambiguous compound reference',
    evidence_ids: ['issue-evidence'],
    related_fact_id: null,
  }],
  stats: {},
  analysis_status: 'disabled',
  extraction_mode: 'deterministic',
}

const EMPTY_TEXT = 'No adopted measurements or extraction notices were recorded.'

describe('PatentAnalysisPane', () => {
  it('reports the deterministic result, keeps assays and species separate and links every fact to its evidence', () => {
    const onOpenEvidence = vi.fn()
    render(<PatentAnalysisPane facts={facts} onOpenEvidence={onOpenEvidence} />)

    expect(screen.getByText('Rule extraction')).toBeInTheDocument()
    expect(screen.getByText('Deterministic result')).toBeInTheDocument()
    expect(screen.getByText('Committed facts and file projection are current.')).toBeInTheDocument()

    const table = screen.getByRole('table')
    expect(within(table).getAllByRole('row')).toHaveLength(3)
    expect(within(table).getByText('human MRGPRX2 HEK293')).toBeInTheDocument()
    expect(within(table).getByText('mouse Mrgprb2 mast cells')).toBeInTheDocument()
    expect(within(table).getByText('< 100 nM')).toBeInTheDocument()
    expect(within(table).getByText('> 2 µM')).toBeInTheDocument()
    fireEvent.click(within(table).getAllByRole('button', { name: '2 sources' })[0])
    fireEvent.click(screen.getByRole('button', { name: /Source 2.*method-0/ }))
    expect(onOpenEvidence).toHaveBeenCalledWith('method-0')

    // Extraction notices stay readable and reach their own source.
    expect(screen.getByText('measurement has no unambiguous compound reference')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Open source evidence' }))
    expect(onOpenEvidence).toHaveBeenCalledWith('issue-evidence')

    // Measurements without notices are a populated result, not an empty pane.
    cleanup()
    render(<PatentAnalysisPane facts={{ ...facts, issues: [] }} onOpenEvidence={onOpenEvidence} />)
    expect(screen.queryByText('Extraction notices (1)')).not.toBeInTheDocument()
    expect(screen.queryByText(EMPTY_TEXT)).not.toBeInTheDocument()
    expect(screen.getByRole('table')).toBeInTheDocument()

    cleanup()
    render(<PatentAnalysisPane facts={{ ...facts, measurements: [], assay_methods: [], issues: [] }} onOpenEvidence={onOpenEvidence} />)
    expect(screen.getByText(EMPTY_TEXT)).toBeInTheDocument()
    expect(screen.getByText('No adopted measurements.')).toBeInTheDocument()
  })
})
