import { fireEvent, render, screen } from '@testing-library/react'
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

describe('MarkushReviewPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the empty placeholder when no candidate is selected', () => {
    render(
      <MarkushReviewPanel
        candidate={null}
        loading={false}
        saving={false}
        libraryRoot="/tmp/lib"
        onDecide={() => {}}
        onUpdate={() => {}}
      />,
    )
    expect(screen.getByText('选择候选以进行审查。')).toBeInTheDocument()
  })

  it('disables confirm buttons after the candidate is rejected', () => {
    const onDecide = vi.fn()
    const rejected: MarkushCandidateDetail = {
      ...candidate,
      review_status: 'rejected',
      review_version: 2,
    }
    render(
      <MarkushReviewPanel
        candidate={rejected}
        loading={false}
        saving={false}
        libraryRoot="/tmp/lib"
        onDecide={onDecide}
        onUpdate={() => {}}
      />,
    )
    const confirmButtons = screen.getAllByRole('button')
    // All confirm_* + reject buttons must be disabled because review_status !== pending
    for (const button of confirmButtons) {
      if (button.textContent && /confirm/i.test(button.textContent)) {
        expect(button).toBeDisabled()
      }
    }
  })

  it('fires onDecide when the reject button is clicked', () => {
    const onDecide = vi.fn()
    render(
      <MarkushReviewPanel
        candidate={candidate}
        loading={false}
        saving={false}
        libraryRoot="/tmp/lib"
        onDecide={onDecide}
        onUpdate={() => {}}
      />,
    )
    const buttons = screen.getAllByRole('button')
    const rejectButton = buttons.find(
      (btn) => btn.textContent && btn.textContent.includes('驳回'),
    )
    expect(rejectButton).toBeDefined()
    fireEvent.click(rejectButton as HTMLElement)
    expect(onDecide).toHaveBeenCalledWith('reject')
  })

  it('shows server eligibility reasons and does not render enumeration when blocked', () => {
    const blocked: MarkushCandidateDetail = {
      ...candidate,
      fragment_id: 'frag-1',
      enumeration_eligible: false,
      enumeration_block_reasons: ['candidate is not a confirmed scaffold'],
    }
    render(
      <MarkushReviewPanel
        candidate={blocked}
        loading={false}
        saving={false}
        libraryRoot="/tmp/lib"
        onDecide={() => {}}
        onUpdate={() => {}}
      />,
    )
    expect(screen.getByText('枚举暂不可用')).toBeInTheDocument()
    expect(
      screen.getByText('· candidate is not a confirmed scaffold'),
    ).toBeInTheDocument()
    expect(screen.queryByTestId('markush-enumeration-panel')).not.toBeInTheDocument()
  })

  it('does not show the blocked hint when enumeration is eligible', () => {
    const eligible: MarkushCandidateDetail = {
      ...candidate,
      scaffold_id: 'sc-1',
      enumeration_eligible: true,
      enumeration_block_reasons: [],
    }
    render(
      <MarkushReviewPanel
        candidate={eligible}
        loading={false}
        saving={false}
        libraryRoot="/tmp/lib"
        onDecide={() => {}}
        onUpdate={() => {}}
      />,
    )
    expect(screen.queryByText('枚举暂不可用')).not.toBeInTheDocument()
    expect(screen.getByTestId('markush-enumeration-panel')).toBeInTheDocument()
  })
})