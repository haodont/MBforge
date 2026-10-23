import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { vi } from 'vitest'

import { createQueryClient } from '../../client'
import { queryKeys } from '../../keys'
import type { DocumentInfo } from '../../../http/library'
import { useDeleteDocuments } from '../useDocuments'
import { useConfigureLibrary } from '../useLibraryStatus'

const deleteDocumentsMock = vi.fn<(docIds: string[]) => Promise<{ success: boolean }>>()

vi.mock('../../../http/library', () => ({
  deleteDocuments: (docIds: string[]) => deleteDocumentsMock(docIds),
  importDocument: vi.fn(),
  listDocuments: vi.fn(),
  getLibraryStatus: vi.fn(),
  configureLibrary: vi.fn().mockResolvedValue({ success: true }),
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

it('discards old documents and late responses when the active library changes', async () => {
  const client = createQueryClient()
  const previous = { documents: [makeDocument('old-library-doc')] }
  client.setQueryData(queryKeys.documents.list(), previous)
  let finish!: (value: typeof previous) => void
  const pending = new Promise<typeof previous>(resolve => { finish = resolve })
  const request = client.query({ queryKey: queryKeys.documents.list(), queryFn: () => pending, staleTime: 0 }).catch(() => undefined)
  const { result } = renderHook(() => useConfigureLibrary(), { wrapper: makeWrapper(client) })
  await act(async () => { await result.current.mutateAsync('new-library') })
  finish(previous)
  await request
  expect(client.getQueryData(queryKeys.documents.list())).toBeUndefined()
})

describe('useDeleteDocuments', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('removes deletions optimistically, invalidates the review cache, and rolls back on failure', async () => {
    const client = createQueryClient()
    client.setQueryData(queryKeys.documents.list(), {
      documents: [makeDocument('doc-1'), makeDocument('doc-2')],
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
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    // The doc's review-center molecules are gone server-side; the review
    // cache must be invalidated so an open review center refetches.
    await waitFor(() => {
      expect(client.getQueryState(queryKeys.review.all)?.isInvalidated).toBe(true)
    })

    // A failed deletion must restore the snapshot it optimistically removed.
    const failingClient = createQueryClient()
    const snapshot = { documents: [makeDocument('doc-1')] }
    failingClient.setQueryData(queryKeys.documents.list(), snapshot)
    deleteDocumentsMock.mockRejectedValue(new Error('delete failed'))

    const failing = renderHook(() => useDeleteDocuments(), {
      wrapper: makeWrapper(failingClient),
    })
    act(() => {
      failing.result.current.mutate(['doc-1'])
    })
    await waitFor(() => expect(failing.result.current.isError).toBe(true))
    expect(failingClient.getQueryData(queryKeys.documents.list())).toEqual(snapshot)
  })
})
