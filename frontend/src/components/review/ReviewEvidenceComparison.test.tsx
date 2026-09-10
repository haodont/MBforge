import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ReviewQueueItem } from '@/api/http/review'

const api = vi.hoisted(() => ({ smilesToRdkitSvg: vi.fn() }))
vi.mock('@/api/http/molecule', () => api)

import ReviewEvidenceComparison from './ReviewEvidenceComparison'

const item: ReviewQueueItem = {
  id: 'review-1',
  kind: 'low_conf_molecule',
  doc_id: 'document-1',
  page: 3,
  bbox: [12, 24, 48, 96],
  crop_relpath: 'crop.png',
  smiles: 'CCO',
  name: 'ethanol',
  confidence: 0.4,
  reasons: [],
  context_text: null,
  status: 'pending',
  payload: {},
  created_at: null,
  resolved_at: null,
}

describe('ReviewEvidenceComparison', () => {
  it('shows source-first evidence and opens its original PDF with the nullable bbox preserved', async () => {
    const onOpenPdf = vi.fn()
    api.smilesToRdkitSvg.mockResolvedValue('<svg><title>ethanol</title></svg>')

    render(
      <ReviewEvidenceComparison
        item={item}
        cropUrl="/api/crops/document-1/crop.png"
        libraryRoot="/library"
        onOpenPdf={onOpenPdf}
      />,
    )

    expect(screen.getByRole('img', { name: '来源结构图' })).toHaveAttribute('src', '/api/crops/document-1/crop.png')
    expect(screen.getByText('来源：document-1 · 第 3 页')).toBeInTheDocument()
    expect(screen.getByText('CCO')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '打开原文' }))
    expect(onOpenPdf).toHaveBeenCalledWith('document-1', 3, [12, 24, 48, 96])

    await waitFor(() => expect(api.smilesToRdkitSvg).toHaveBeenCalledWith('CCO'))
    expect(screen.getByRole('img', { name: 'RDKit 2D 结构图' })).toHaveAttribute(
      'src',
      expect.stringContaining('data:image/svg+xml;charset=utf-8,'),
    )
  })

  it('states missing source crop and RDKit rendering failure explicitly', async () => {
    api.smilesToRdkitSvg.mockRejectedValue(new Error('render unavailable'))

    render(
      <ReviewEvidenceComparison
        item={{ ...item, doc_id: null, page: null, bbox: null }}
        cropUrl={null}
        libraryRoot={null}
        onOpenPdf={vi.fn()}
      />,
    )

    expect(screen.getByText('暂无来源结构图')).toBeInTheDocument()
    expect(screen.getByText('来源：无来源文档')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '打开原文' })).toBeDisabled()
    expect(await screen.findByText('RDKit 2D 结构图生成失败：render unavailable')).toBeInTheDocument()
  })
})
