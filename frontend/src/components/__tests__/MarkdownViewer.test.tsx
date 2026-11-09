import { fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { openTab } = vi.hoisted(() => ({ openTab: vi.fn() }))

vi.mock('@/context/AppContext', () => ({
  useAppContext: () => ({ openTab }),
}))

vi.mock('@/api/query/hooks', () => ({
  useDocumentMarkdown: vi.fn(),
}))

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: () => {} },
  useTranslation: () => ({
    t: (key: string, params?: Record<string, string>) =>
      key === 'md.openPdfPage' ? `Open PDF page ${params?.page}` : key,
  }),
}))

import { useDocumentMarkdown } from '@/api/query/hooks'
import type { DocumentEntry } from '@/types'
import MarkdownViewer from '../MarkdownViewer'

const doc = {
  doc_id: 'doc-1',
  path: '/tmp/doc.pdf',
  doc_type: 'pdf',
  title: 'Test patent',
} as DocumentEntry

describe('MarkdownViewer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(useDocumentMarkdown).mockReturnValue({
      data: {
        ok: true,
        text: '# Claim 1\n\n<!-- PAGE 3 -->\n\nA compound of formula I.',
      },
      isLoading: false,
    } as never)
  })

  it('builds a table of contents and opens the PDF at a page marker', () => {
    render(<MarkdownViewer libraryRoot="/lib" doc={doc} onClose={vi.fn()} />)

    const toc = screen.getByRole('navigation', { name: 'md.toc' })
    expect(within(toc).getByRole('button', { name: 'Claim 1' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Open PDF page 3' }))

    expect(openTab).toHaveBeenCalledWith({
      type: 'pdf',
      title: 'Test patent',
      doc,
      libraryRoot: '/lib',
      initialPage: 3,
    })
  })
})
