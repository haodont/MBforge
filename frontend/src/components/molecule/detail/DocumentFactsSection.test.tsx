import { render, screen } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { createQueryClient } from '@/api/query/client'
import DocumentFactsSection from './DocumentFactsSection'
import type { PatentFactsArtifact } from '@/api/http/library'

const facts: PatentFactsArtifact = {
  doc_id: 'doc-1',
  run_id: 'run-1',
  sections: [],
  entries: [],
  names: [
    {
      name_id: 'name-1',
      label_key: '@example:1',
      label_raw: '实施例1',
      name_raw: 'N-(5-(3,5-二氟苄基)噻唑-2-基)-2-甲基丙硫酰胺',
      name_clean: 'N-(5-(3,5-二氟苄基)噻唑-2-基)-2-甲基丙硫酰胺',
      page: 95,
      evidence_ids: ['ev-1'],
      attribution: 'resolved',
    },
  ],
  characterizations: [
    {
      characterization_id: 'char-1',
      technique: 'nmr',
      raw_text: '1H NMR (400 MHz, CDCl3) δ 7.42 (s, 1H)。',
      label_key: '@example:1',
      page: 95,
      evidence_ids: ['ev-1'],
      attribution: 'resolved',
    },
    {
      characterization_id: 'char-2',
      technique: 'ms',
      raw_text: 'MS (ESI) m/z: 456.2 [M+H]+',
      label_key: '',
      page: 95,
      evidence_ids: ['ev-2'],
      attribution: 'unresolved',
    },
  ],
  synthesis_steps: [
    {
      route_id: 'route-1',
      section_id: 'sec-1',
      kind: 'example',
      title: '实施例1：化合物1的制备',
      label_raw: '实施例1',
      label_key: '@example:1',
      product_label: '',
      page_start: 95,
      page_end: 95,
      evidence_ids: ['ev-1'],
      steps: [{ step_no: 1, text: '步骤1：将中间体与酸反应。', evidence_ids: ['ev-1'] }],
      step_count: 1,
      yield_raw: '收率41%',
      method_note: '',
      attribution: 'resolved',
    },
  ],
  assay_methods: [],
  examples: [],
  measurements: [],
  issues: [],
  stats: {},
}

vi.mock('@/api/query/hooks/useDocumentArtifacts', () => ({
  useDocumentPatentFacts: () => ({ isLoading: false, data: { ok: true, data: facts } }),
}))

vi.mock('@/api/http/library', () => ({
  resolveDocumentEvidenceBatch: vi.fn(() => Promise.resolve([])),
}))

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
  initReactI18next: { type: '3rdParty', init: () => {} },
}))

function renderSection() {
  const client = createQueryClient()
  return render(
    <QueryClientProvider client={client}>
      <DocumentFactsSection docId="doc-1" labelKeys={['@example:1']} libraryRoot="/lib" />
    </QueryClientProvider>,
  )
}

describe('DocumentFactsSection', () => {
  it('shows the printed name, spectra and route, and only this compound', () => {
    renderSection()

    expect(screen.getByTestId('molecule-document-facts')).toBeTruthy()
    expect(screen.getByText('molecule.facts.names')).toBeTruthy()
    expect(
      screen.getByText('N-(5-(3,5-二氟苄基)噻唑-2-基)-2-甲基丙硫酰胺'),
    ).toBeTruthy()
    expect(screen.getByText('1H NMR (400 MHz, CDCl3) δ 7.42 (s, 1H)。')).toBeTruthy()
    expect(screen.getByText('收率41%')).toBeTruthy()
    expect(screen.getByText('步骤1：将中间体与酸反应。')).toBeTruthy()

    // The unattributed MS line carries no key, so it is not this compound's fact.
    expect(screen.queryByText('MS (ESI) m/z: 456.2 [M+H]+')).toBeNull()
  })
})
