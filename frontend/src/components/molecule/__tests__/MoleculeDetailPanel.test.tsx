import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: () => {} },
  useTranslation: () => ({
    t: (key: string, params?: Record<string, number>) => {
      if (typeof key !== 'string') return ''
      const dict: Record<string, string> = {
        'evidence.chainTitle': '证据链 · {{count}} 处',
        'evidence.structureComparison': '结构对照',
        'evidence.originalEvidence': '原始证据',
        'evidence.currentEsiles': '当前 E-SMILES 结构',
        'evidence.documentsCount': '{{count}} 篇文献',
        'evidence.showMore': '展开 {{count}} 篇文献',
        'evidence.showLess': '收起文献',
        'evidence.correctionHistory': '修正历史',
        'evidence.rdkitRenderError': 'RDKit 无法渲染此结构',
        'evidence.originalEvidenceAlt': '{{docId}} 原始分子图',
        'evidence.currentRdkitAlt': '当前 E-SMILES 的 RDKit 结构图',
        'evidence.generatingRdkit': '正在生成当前 E-SMILES 结构图…',
        'evidence.kindFigure': '图',
        'evidence.kindText': '文',
        'evidence.kindTable': '表',
        'evidence.pageNumber': '第 {{page}} 页',
        'evidence.textMention': '文本提及',
        'evidence.tableEvidence': '表格',
        'evidence.confidence': '置信度 {{pct}}%',
        'evidence.noLibraryRoot': 'library_root 未配置',
        'evidence.openInPdf': '在 PDF 查看器中打开',
        'evidence.openOriginal': '打开原文',
      }
      let value = dict[key] ?? key
      if (params) {
        for (const [k, v] of Object.entries(params)) {
          value = value.replace(`{{${k}}}`, String(v))
        }
      }
      return value
    },
  }),
}))

import { molAdminUpdate } from '@/api/http/molecule_admin'
import MoleculeDetailPanel from '../MoleculeDetailPanel'
import type { MoleculeRecord } from '@/types'

vi.mock('@/api/http/molecule', () => ({
  smilesToRdkitSvg: vi.fn().mockResolvedValue('<svg />'),
  chemDescriptors: vi.fn().mockResolvedValue({
    molecular_weight: 46.07,
    logp: -0.3,
    tpsa: 20.2,
    hba: 1,
    hbd: 1,
    rotatable_bonds: 0,
    formula: 'C2H6O',
  }),
}))

vi.mock('@/api/http/molecule_admin', () => ({
  molAdminUpdate: vi.fn().mockResolvedValue(true),
}))

vi.mock('@/hooks/useToast', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

vi.mock('../MoleculeEditorDialog', () => ({
  default: ({ onSave, originalImageUrl }: {
    onSave: (smiles: string) => Promise<void>
    originalImageUrl?: string | null
  }) => (
    <div>
      {originalImageUrl && <img alt="editor original image" src={originalImageUrl} />}
      <button onClick={() => void onSave('CCN')}>Save visual structure</button>
    </div>
  ),
}))

const molecule: MoleculeRecord = {
  mol_id: 'mol-1',
  esmiles: 'CCO',
  name: 'Test',
  source_doc: 'doc-1',
  source_type: 'image',
  activity: null,
  activity_type: '',
  units: '',
  status: 'pending',
  properties: {},
  tags: [],
  notes: '',
  created_at: '2026-01-01T00:00:00Z',
  evidence: [
    {
      id: 1,
      doc_id: 'doc-1',
      page: 2,
      bbox: null,
      crop_url: '/source-crop.png',
      context_text: 'Compound 7 inhibited the target at 12 nM.',
      code_text: null,
      role: 'primary',
      kind: 'figure',
      confidence: 0.9,
      source_type: 'text',
      created_at: '2026-01-01T00:00:00Z',
    },
    {
      id: 2,
      doc_id: 'doc-1',
      page: 3,
      bbox: null,
      crop_url: null,
      context_text: 'Compound 7 inhibited the target at 12 nM.',
      code_text: null,
      role: 'supporting',
      kind: 'text',
      confidence: 0.8,
      source_type: 'text',
      created_at: '2026-01-01T00:00:00Z',
    },
  ],
}

describe('MoleculeDetailPanel', () => {
  it('persists a visual structure correction without an approval step', async () => {
    const onSaved = vi.fn()
    render(
      <MoleculeDetailPanel
        molecule={molecule}
        libraryRoot="C:/library"
        onSaved={onSaved}
      />,
    )

    expect(screen.getByTestId('molecule-detail-panel')).toHaveClass('molecule-detail-panel')

    fireEvent.click(screen.getByRole('button', { name: /编辑结构/ }))
    expect(screen.getByAltText('editor original image')).toHaveAttribute('src', '/source-crop.png')
    fireEvent.click(screen.getByRole('button', { name: 'Save visual structure' }))

    await waitFor(() => {
      expect(molAdminUpdate).toHaveBeenCalledWith(
        'C:/library',
        expect.objectContaining({ esmiles: 'CCN', status: 'corrected' }),
      )
    })
    expect(onSaved).toHaveBeenCalledOnce()
  })

  it('deduplicates related evidence text and places notes last', () => {
    render(
      <MoleculeDetailPanel
        molecule={molecule}
        libraryRoot="C:/library"
      />,
    )

    expect(screen.getByText('相关文本')).toBeInTheDocument()
    expect(screen.getAllByText('Compound 7 inhibited the target at 12 nM.')).toHaveLength(1)

    const panel = screen.getByTestId('molecule-detail-panel')
    const notes = screen.getByText('备注').closest('label')
    expect(panel.lastElementChild).toBe(notes)
  })

  it('shows the source crop beside the current E-SMILES structure', () => {
    render(<MoleculeDetailPanel molecule={molecule} libraryRoot="C:/library" />)

    expect(screen.getByLabelText('结构对照')).toBeInTheDocument()
    expect(screen.getByText('原始证据')).toBeInTheDocument()
    expect(screen.getByText('当前 E-SMILES 结构')).toBeInTheDocument()
    expect(screen.getAllByText('E-SMILES')).toHaveLength(1)
  })

  it('places the evidence chain before the editable record fields', () => {
    render(<MoleculeDetailPanel molecule={molecule} libraryRoot="C:/library" />)

    const panelText = screen.getByTestId('molecule-detail-panel').textContent
    expect(panelText.indexOf('证据链 · 2 处')).toBeLessThan(panelText.indexOf('名称'))
  })
})
