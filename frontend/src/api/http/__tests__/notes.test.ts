/**
 * notes.ts — note storage wrappers (covered module at top).
 *
 * The contract worth keeping is the snake_case `library_root` envelope the
 * backend expects (a camelCase slip here silently breaks every note route)
 * plus the `notes` array unwrap.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { notesList, notesSave, notesDelete, notesBacklinks } from '../notes'

vi.mock('../_utils', () => ({
  httpPost: vi.fn(),
  invokeWithError: vi.fn((fn: () => Promise<unknown>) => fn()),
}))

import { httpPost } from '../_utils'

const mockHttpPost = vi.mocked(httpPost)

const note = {
  id: 'n1',
  title: 'Note',
  content: 'content',
  tags: [],
  links: [],
  createdAt: '',
  updatedAt: '',
}

describe('notes API', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('sends the library_root payload and unwraps note envelopes', async () => {
    mockHttpPost.mockResolvedValue({ success: true, notes: [note] })
    await expect(notesList('/lib')).resolves.toEqual([note])
    expect(mockHttpPost).toHaveBeenCalledWith('/api/v1/notes/list', { library_root: '/lib' })

    const saved = await (async () => {
      mockHttpPost.mockResolvedValue({ success: true, note })
      return notesSave('/lib', note)
    })()
    expect(saved).toEqual(note)
    expect(mockHttpPost).toHaveBeenLastCalledWith('/api/v1/notes/save', { library_root: '/lib', note })

    mockHttpPost.mockResolvedValue({ success: true })
    await expect(notesDelete('/lib', 'n1')).resolves.toBe(true)
    expect(mockHttpPost).toHaveBeenLastCalledWith('/api/v1/notes/delete', { library_root: '/lib', id: 'n1' })

    mockHttpPost.mockResolvedValue({ success: true, notes: [note] })
    await expect(notesBacklinks('/lib', 'n1')).resolves.toEqual([note])
    expect(mockHttpPost).toHaveBeenLastCalledWith('/api/v1/notes/backlinks', {
      library_root: '/lib',
      targetId: 'n1',
    })
  })
})
