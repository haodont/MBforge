/** Notes API — project-level note storage via HTTP. */

import { httpPost, invokeWithError } from './_utils'
import { ErrorCode } from '@/utils/errors'

export interface NoteLink {
  type: 'molecule' | 'document' | 'session' | 'note'
  refId: string
  refTitle: string
}

export interface Note {
  id: string
  title: string
  content: string
  tags: string[]
  links: NoteLink[]
  createdAt: string
  updatedAt: string
}

export async function notesList(root: string): Promise<Note[]> {
  const resp = await invokeWithError(
    () => httpPost<{ success: boolean; notes: Note[] }>('/api/v1/notes/list', { library_root: root }),
    ErrorCode.ApiError,
  )
  return resp.notes
}

export async function notesSave(root: string, note: Note): Promise<Note> {
  const resp = await invokeWithError(
    () => httpPost<{ success: boolean; note: Note }>('/api/v1/notes/save', { library_root: root, note }),
    ErrorCode.ApiError,
  )
  return resp.note
}

export async function notesDelete(root: string, id: string): Promise<boolean> {
  const resp = await invokeWithError(
    () => httpPost<{ success: boolean }>('/api/v1/notes/delete', { library_root: root, id }),
    ErrorCode.ApiError,
  )
  return resp.success
}

/** 返回引用了目标笔记的其他笔记列表（反向链接）. */
export async function notesBacklinks(root: string, targetId: string): Promise<Note[]> {
  const resp = await invokeWithError(
    () => httpPost<{ success: boolean; notes: Note[] }>('/api/v1/notes/backlinks', { library_root: root, targetId }),
    ErrorCode.ApiError,
  )
  return resp.notes
}
