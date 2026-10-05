import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { vi } from 'vitest'

import { createQueryClient } from '../../client'
import { queryKeys } from '../../keys'
import type { DocumentInfo } from '../../../http/library'
import { useDeleteDocuments } from '../useDocuments'

const deleteDocumentsMock = vi.fn<(docIds: string[]) => Promise<{ success: boolean }>>()

vi.mock('../../../http/library', () => ({
  deleteDocuments: (docIds: string[]) => deleteDocumentsMock(docIds),
  importDocument: vi.fn(),
  listDocuments: vi.fn(),
}))

function makeDocument(docId: string): DocumentInfo {
  return {
    doc_id: docId,
    title: docId,
    file_name: `${docId}.pdf`,
    page_count: 1,
    status: 'ready',
    created_at: '2026-07-13T00:00:00Z',
  }
}

function makeWrapper(client: ReturnType<typeof createQueryClient>) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

describe('useDeleteDocuments', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('removes a document from every cached collection immediately', async () => {
    const client = createQueryClient()
    client.setQueryData(queryKeys.documents.list(), {
      documents: [makeDocument('doc-1'), makeDocument('doc-2')],
    })
    client.setQueryData(queryKeys.documents.list('collection-a'), {
      documents: [makeDocument('doc-1')],
    })
    client.setQueryData(queryKeys.review.all, { stale: 'review-cache' })
    deleteDocumentsMock.mockResolvedValue({ success: true })

    const { result } = renderHook(() => useDeleteDocuments(), {
      wrapper: makeWrapper(client),
    })

    act(() => {
      result.current.mutate(['doc-1'])
    })

    await waitFor(() => {
      expect(client.getQueryData(queryKeys.documents.list())).toEqual({
        documents: [makeDocument('doc-2')],
      })
      expect(client.getQueryData(queryKeys.documents.list('collection-a'))).toEqual({
        documents: [],
      })
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    // The doc's review-center molecules are gone server-side; the review
    // cache must be invalidated so an open review center refetches.
    await waitFor(() => {
      expect(client.getQueryState(queryKeys.review.all)?.isInvalidated).toBe(true)
    })
  })

  it('restores cached lists when deletion fails', async () => {
    const client = createQueryClient()
    const previous = { documents: [makeDocument('doc-1')] }
    client.setQueryData(queryKeys.documents.list(), previous)
    deleteDocumentsMock.mockRejectedValue(new Error('delete failed'))

    const { result } = renderHook(() => useDeleteDocuments(), {
      wrapper: makeWrapper(client),
    })

    act(() => {
      result.current.mutate(['doc-1'])
    })

    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(client.getQueryData(queryKeys.documents.list())).toEqual(previous)
  })
})
