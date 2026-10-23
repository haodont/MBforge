import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: () => {} },
  useTranslation: () => ({
    t: (key: string, fallbackOrParams?: string | Record<string, unknown>, params?: Record<string, unknown>) => {
      if (typeof fallbackOrParams === 'string') return fallbackOrParams
      if (fallbackOrParams && typeof fallbackOrParams === 'object') {
        return Object.entries(fallbackOrParams).reduce(
          (acc, [k, v]) => acc.replace(`{{${k}}}`, String(v)),
          key,
        )
      }
      if (params) {
        return Object.entries(params).reduce(
          (acc, [k, v]) => acc.replace(`{{${k}}}`, String(v)),
          key,
        )
      }
      return key
    },
  }),
}))

import MarkushQueue from '../MarkushQueue'
import type { MarkushCandidate } from '@/api/http/markush'

const baseCandidate: MarkushCandidate = {
  candidate_id: 'c-1',
  source_key: 'doc-1|1|10.0,20.0,110.0,220.0|R1',
  doc_id: 'doc-1',
  predicted_role: 'review_required',
  smiles: '*c1ccccc1',
  esmiles: '*c1ccccc1',
  name: '',
  raw_label: 'R1',
  normalized_label: 'R1',
  label_kind: 'r_group',
  page: 1,
  bbox_x0: 10,
  bbox_y0: 20,
  bbox_x1: 110,
  bbox_y1: 220,
  crop_relpath: null,
  moldet_confidence: null,
  scribe_confidence: null,
  composite_confidence: 0.9,
  reasons: ['context_formula_label'],
  context_text: '',
  properties: {},
  recognition_status: 'valid',
  review_status: 'pending',
  review_version: 1,
  superseded_at: null,
  created_at: null,
  updated_at: null,
}

const baseProps = {
  title: 'Queue',
  filterStatus: 'pending',
  onFilterChange: () => {},
  selectedCandidateId: null,
  onSelect: () => {},
}

describe('MarkushQueue', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the loading, error and empty states of the queue', () => {
    render(<MarkushQueue {...baseProps} loading error={null} items={[]} total={0} />)
    expect(screen.getByText('加载中…')).toBeInTheDocument()
    cleanup()

    render(<MarkushQueue {...baseProps} loading={false} error="boom" items={[]} total={0} />)
    expect(screen.getByText('boom')).toBeInTheDocument()
    cleanup()

    render(<MarkushQueue {...baseProps} loading={false} error={null} items={[]} total={0} />)
    expect(screen.getByTestId('markush-empty')).toBeInTheDocument()
  })

  it('renders one row per candidate, groups them by formula context and fires onSelect on click', () => {
    const formula = {
      ...baseCandidate,
      candidate_id: 'c-formula',
      normalized_label: 'Formula I',
      label_kind: 'formula' as const,
      predicted_role: 'scaffold' as const,
    }
    const fragment = {
      ...baseCandidate,
      candidate_id: 'c-fragment',
      predicted_role: 'fragment' as const,
      properties: { formula_label: 'Formula (I)' },
    }
    const unlinked = {
      ...baseCandidate,
      candidate_id: 'c-unlinked',
      doc_id: 'doc-2',
    }
    const onSelect = vi.fn()

    render(
      <MarkushQueue
        {...baseProps}
        loading={false}
        error={null}
        items={[baseCandidate, formula, fragment, unlinked]}
        total={4}
        onSelect={onSelect}
      />,
    )

    const rows = screen.getAllByTestId('markush-queue-row')
    expect(rows).toHaveLength(4)
    expect(screen.getByText('Formula I · doc-1')).toBeInTheDocument()
    expect(screen.getByText('未关联通式 · doc-2')).toBeInTheDocument()
    expect(screen.getByText('骨架')).toBeInTheDocument()
    expect(screen.getByText('片段')).toBeInTheDocument()

    fireEvent.click(rows[0])
    expect(onSelect).toHaveBeenCalledWith('c-1')
  })
})
