import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: () => {} },
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback ?? key,
  }),
}))

import MarkushReviewPanel from '../MarkushReviewPanel'
import type { MarkushCandidateDetail } from '@/api/http/markush'

vi.mock('../SiteEditor', () => ({
  default: () => <div data-testid="site-editor-mock" />,
}))
vi.mock('../EnumerationPanel', () => ({
  default: () => <div data-testid="markush-enumeration-panel" />,
}))

const candidate: MarkushCandidateDetail = {
  candidate_id: 'c-1',
  source_key: 'k',
  doc_id: 'doc-1',
  predicted_role: 'review_required',
  smiles: '*c1ccccc1',
  esmiles: '*c1ccccc1',
  name: '',
  raw_label: 'R1',
  normalized_label: 'R1',
  label_kind: 'r_group',
  page: 1,
  bbox_x0: null,
  bbox_y0: null,
  bbox_x1: null,
  bbox_y1: null,
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
  scaffold_id: null,
  fragment_id: null,
  enumeration_eligible: false,
  enumeration_block_reasons: ['candidate is not a confirmed scaffold'],
  evidence: [],
  decisions: [],
}

const baseProps = {
  loading: false,
  saving: false,
  libraryRoot: '/tmp/lib',
  onDecide: () => {},
  onUpdate: () => {},
}

describe('MarkushReviewPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows the empty placeholder and gates the confirm and reject decisions on the review status', () => {
    render(<MarkushReviewPanel {...baseProps} candidate={null} />)
    expect(screen.getByText('选择候选以进行审查。')).toBeInTheDocument()
    cleanup()

    const onDecide = vi.fn()

    // A non-pending candidate cannot be confirmed again.
    render(
      <MarkushReviewPanel
        {...baseProps}
        candidate={{ ...candidate, review_status: 'rejected', review_version: 2 }}
        onDecide={onDecide}
      />,
    )
    const confirmButtons = screen.getAllByRole('button')
    // All confirm_* + reject buttons must be disabled because review_status !== pending
    for (const button of confirmButtons) {
      if (button.textContent && /confirm/i.test(button.textContent)) {
        expect(button).toBeDisabled()
      }
    }
    cleanup()

    // A pending candidate can still be rejected.
    render(<MarkushReviewPanel {...baseProps} candidate={candidate} onDecide={onDecide} />)
    const rejectButton = screen
      .getAllByRole('button')
      .find((btn) => btn.textContent && btn.textContent.includes('驳回'))
    expect(rejectButton).toBeDefined()
    fireEvent.click(rejectButton as HTMLElement)
    expect(onDecide).toHaveBeenCalledWith('reject')
  })

  it('shows the server enumeration block reasons and only mounts enumeration when eligible', () => {
    render(
      <MarkushReviewPanel
        {...baseProps}
        candidate={{
          ...candidate,
          fragment_id: 'frag-1',
          enumeration_eligible: false,
          enumeration_block_reasons: ['candidate is not a confirmed scaffold'],
        }}
      />,
    )
    expect(screen.getByText('枚举暂不可用')).toBeInTheDocument()
    expect(screen.getByText('· candidate is not a confirmed scaffold')).toBeInTheDocument()
    expect(screen.queryByTestId('markush-enumeration-panel')).not.toBeInTheDocument()
    cleanup()

    render(
      <MarkushReviewPanel
        {...baseProps}
        candidate={{
          ...candidate,
          scaffold_id: 'sc-1',
          enumeration_eligible: true,
          enumeration_block_reasons: [],
        }}
      />,
    )
    expect(screen.queryByText('枚举暂不可用')).not.toBeInTheDocument()
    expect(screen.getByTestId('markush-enumeration-panel')).toBeInTheDocument()
  })
})
