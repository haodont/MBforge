import { describe, it, expect, vi, beforeEach } from 'vitest'
import { notesList, notesSave, notesDelete, notesBacklinks } from '../notes'

vi.mock('../_utils', () => ({
  httpPost: vi.fn(),
  invokeWithError: vi.fn((fn: () => Promise<unknown>) => fn()),
}))

import { httpPost } from '../_utils'

const mockHttpPost = vi.mocked(httpPost)

describe('notes API', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('sends library_root (not libraryRoot) for list', async () => {
    mockHttpPost.mockResolvedValue({ success: true, notes: [] })
    await notesList('/lib')
    expect(mockHttpPost).toHaveBeenCalledWith('/api/v1/notes/list', { library_root: '/lib' })
  })

  it('sends library_root for save', async () => {
    const note = {
      id: 'n1',
      title: 'Note',
      content: 'content',
      tags: [],
      links: [],
      createdAt: '',
      updatedAt: '',
    }
    mockHttpPost.mockResolvedValue({ success: true, note })
    await notesSave('/lib', note)
    expect(mockHttpPost).toHaveBeenCalledWith('/api/v1/notes/save', { library_root: '/lib', note })
  })

  it('sends library_root for delete', async () => {
    mockHttpPost.mockResolvedValue({ success: true })
    await notesDelete('/lib', 'n1')
    expect(mockHttpPost).toHaveBeenCalledWith('/api/v1/notes/delete', { library_root: '/lib', id: 'n1' })
  })

  it('sends library_root for backlinks', async () => {
    mockHttpPost.mockResolvedValue({ success: true, notes: [] })
    await notesBacklinks('/lib', 'n1')
    expect(mockHttpPost).toHaveBeenCalledWith('/api/v1/notes/backlinks', { library_root: '/lib', targetId: 'n1' })
  })
})
