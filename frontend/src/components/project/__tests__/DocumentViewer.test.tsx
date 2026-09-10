import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

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

  it('mounts the PDF workbench that owns the comparison side panel', () => {
    render(<DocumentViewer doc={mockDoc} libraryRoot="/tmp/lib" onClose={vi.fn()} />)
    expect(screen.getByTestId('pdf-viewer')).toBeInTheDocument()
    expect(screen.getByText('PDF').closest('.document-viewer-pane')).toBeInTheDocument()
    expect(pdfViewerProps.current).toMatchObject({
      doc: mockDoc,
      libraryRoot: '/tmp/lib',
    })
    expect(pdfViewerProps.current?.onMoleculeClick).toEqual(expect.any(Function))
  })

  it('keeps the page-navigation callback stable for the comparison pane', () => {
    const view = render(<DocumentViewer doc={mockDoc} libraryRoot="/tmp/lib" onClose={vi.fn()} />)
    const firstCallback = pdfViewerProps.current?.onMoleculeClick
    expect(firstCallback).toEqual(expect.any(Function))
    view.rerender(<DocumentViewer doc={mockDoc} libraryRoot="/tmp/lib" onClose={vi.fn()} />)
    expect(pdfViewerProps.current?.onMoleculeClick).toEqual(firstCallback)
  })

  it('passes PDF deep-link page and bbox to the viewer', () => {
    render(
      <DocumentViewer
        doc={mockDoc}
        libraryRoot="/tmp/lib"
        initialPage={4}
        initialBbox={[10, 20, 40, 60]}
        onClose={vi.fn()}
      />,
    )

    expect(pdfViewerProps.current).toMatchObject({
      initialPage: 4,
      initialBbox: [10, 20, 40, 60],
    })
  })
})
