import { describe, it, expect, vi, beforeEach } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'

vi.mock('@/api/query/hooks', () => ({
  useDocumentEvidence: vi.fn(),
}))

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: () => {} },
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en' },
  }),
}))

import { useDocumentEvidence } from '@/api/query/hooks'
import type { DocumentEvidenceItem } from '@/api/http/library'
import PageEvidencePane from '../PageEvidencePane'

function evidence(overrides: Partial<DocumentEvidenceItem>): DocumentEvidenceItem {
  return {
    evidence_id: 'ev-1',
    doc_id: 'doc-1',
    page: 2,
    bbox: [10, 700, 300, 720],
    raw_text: '',
    kind: 'text',
    category: 'text',
    paragraph_id: '',
    paragraph_number: null,
    paragraph_start: false,
    paragraph_line: 0,
    indent_level: 0,
    ...overrides,
  }
}

function mockEvidence(items: DocumentEvidenceItem[]) {
  vi.mocked(useDocumentEvidence).mockReturnValue({
    data: { ok: true, data: items },
    isLoading: false,
  } as unknown as ReturnType<typeof useDocumentEvidence>)
}

function renderPane(selectedEvidenceId?: string) {
  return render(
    <PageEvidencePane
      docId="doc-1"
      page={2}
      libraryRoot="/tmp/lib"
      selectedEvidenceId={selectedEvidenceId}
    />,
  )
}

describe('PageEvidencePane', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // jsdom has no layout, so scrolling must be stubbed.
    Element.prototype.scrollIntoView = vi.fn()
  })

  it('groups paragraph rows into one block and renders continuation, indentation and selection state', () => {
    mockEvidence([
      evidence({
        evidence_id: 'ev-opening',
        raw_text: '[0003] MRGX2 is Gq-coupled … (D.',
        paragraph_id: 'p-0003',
        paragraph_number: '0003',
        paragraph_start: true,
      }),
      evidence({
        evidence_id: 'ev-continuation',
        raw_text: 'Fujisawa et al., J Allergy Clin Immunol …).',
        paragraph_id: 'p-0003',
        paragraph_number: '0003',
      }),
      evidence({
        evidence_id: 'ev-next',
        raw_text: '[0004] MRGX2 is potentially involved …',
        paragraph_id: 'p-0004',
        paragraph_number: '0004',
        paragraph_start: true,
      }),
      evidence({
        evidence_id: 'ev-head',
        raw_text: '[0006] One aspect provides:',
        paragraph_id: 'p-0006',
        paragraph_number: '0006',
        paragraph_start: true,
        paragraph_line: 0,
        indent_level: 0,
      }),
      evidence({
        evidence_id: 'ev-item',
        raw_text: '(a) C1-4 alkyl which is substituted',
        paragraph_id: 'p-0006',
        paragraph_number: '0006',
        paragraph_line: 1,
        indent_level: 1,
      }),
    ])

    const { container } = renderPane()

    // Every row of one paragraph collapses into a single block.
    const blocks = container.querySelectorAll('.pdf-evidence-item')
    expect(blocks).toHaveLength(3)
    expect(blocks[0].querySelector('p')).toHaveTextContent(
      '[0003] MRGX2 is Gq-coupled … (D. Fujisawa et al., J Allergy Clin Immunol …).',
    )
    expect(blocks[1].querySelector('p')).toHaveTextContent(
      '[0004] MRGX2 is potentially involved …',
    )

    // Deeper lines of a paragraph render as separate, indented lines.
    const lines = blocks[2].querySelectorAll<HTMLElement>('p')
    expect(lines).toHaveLength(2)
    expect(lines[0].style.paddingLeft).toBe('')
    expect(lines[1].style.paddingLeft).toBe('1.25em')
    expect(lines[1]).toHaveTextContent('(a) C1-4 alkyl which is substituted')

    cleanup()

    // A paragraph whose first rendered row continues an earlier page is
    // marked as continued, and the block holding the selected evidence row is
    // highlighted.
    mockEvidence([
      evidence({
        evidence_id: 'ev-opening',
        raw_text: '[0003] MRGX2 is Gq-coupled … (D.',
        paragraph_id: 'p-0003',
        paragraph_number: '0003',
        paragraph_start: false,
      }),
      evidence({
        evidence_id: 'ev-continuation',
        raw_text: 'Fujisawa et al., J Allergy Clin Immunol …).',
        paragraph_id: 'p-0003',
        paragraph_number: '0003',
      }),
    ])

    const selected = renderPane('ev-continuation')

    const selectedBlocks = selected.container.querySelectorAll('.pdf-evidence-item')
    expect(selectedBlocks).toHaveLength(1)
    expect(selectedBlocks[0]).toHaveClass('is-selected')
    expect(selectedBlocks[0]).toHaveTextContent('pdf.evidenceContinued')
    expect(screen.getByText('[0003]')).toBeInTheDocument()
  })
})
