import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { QueryClientProvider } from '@tanstack/react-query'
import { createQueryClient } from '@/api/query/client'

const { pdfViewerProps } = vi.hoisted(() => ({
  pdfViewerProps: { current: null as Record<string, unknown> | null },
}))

// Mock child components to isolate DocumentViewer tests.
vi.mock('../PdfViewer', () => ({
  default: vi.fn((props: Record<string, unknown>) => {
    pdfViewerProps.current = props
    return <div data-testid="pdf-viewer">PDF</div>
  }),
  PdfViewerHandle: {} as never,
}))

import DocumentViewer from '../DocumentViewer'

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={createQueryClient()}>{children}</QueryClientProvider>
}

const mockDoc = {
  doc_id: 'test-doc-1',
  path: 'test.pdf',
  doc_type: 'pdf' as const,
  title: 'Test Document',
}

describe('DocumentViewer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('mounts the PDF workbench that owns the comparison side panel, forwards the deep-link target and keeps the navigation callback stable', () => {
    const view = render(
      <DocumentViewer
        doc={mockDoc}
        libraryRoot="/tmp/lib"
        initialPage={4}
        initialBbox={[10, 20, 40, 60]}
        onClose={vi.fn()}
      />,
      { wrapper },
    )

    expect(screen.getByTestId('pdf-viewer')).toBeInTheDocument()
    expect(screen.getByText('PDF').closest('.document-viewer-pane')).toBeInTheDocument()
    expect(pdfViewerProps.current).toMatchObject({
      doc: mockDoc,
      libraryRoot: '/tmp/lib',
      initialPage: 4,
      initialBbox: [10, 20, 40, 60],
    })
    expect(pdfViewerProps.current?.onMoleculeClick).toEqual(expect.any(Function))

    // Re-rendering the pane must not churn the page-navigation callback.
    const firstCallback = pdfViewerProps.current?.onMoleculeClick
    view.rerender(<DocumentViewer doc={mockDoc} libraryRoot="/tmp/lib" onClose={vi.fn()} />)
    expect(pdfViewerProps.current?.onMoleculeClick).toEqual(firstCallback)
  })
})
