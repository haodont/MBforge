/** React Query hooks for notes CRUD. */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { notesList, notesSave, notesDelete, notesBacklinks } from '../../http/notes'
import { queryKeys } from '../keys'
import type { Note } from '../../http/notes'

/** Fetch all notes for a given library root. */
export function useNotes(libraryRoot: string) {
  return useQuery({
    queryKey: queryKeys.notes.list(libraryRoot),
    queryFn: () => notesList(libraryRoot),
    enabled: Boolean(libraryRoot),
  })
}

/** Notes that link *to* the given note (backlinks, one hop). */
export function useNotesBacklinks(libraryRoot: string, targetId: string | null) {
  return useQuery({
    queryKey: queryKeys.notes.backlinks(libraryRoot, targetId ?? ''),
    queryFn: () => notesBacklinks(libraryRoot, targetId as string),
    enabled: Boolean(libraryRoot) && Boolean(targetId),
  })
}

/** Create or update a note. */
export function useSaveNote() {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: ({
      libraryRoot,
      note,
    }: {
      libraryRoot: string
      note: Note
    }) => notesSave(libraryRoot, note),
    onSuccess: (_data, variables) => {
      void qc.invalidateQueries({
        queryKey: queryKeys.notes.list(variables.libraryRoot),
      })
      void qc.invalidateQueries({
        queryKey: queryKeys.notes.backlinks(variables.libraryRoot, variables.note.id),
      })
    },
  })
}

/** Delete a note. */
export function useDeleteNote() {
  const qc = useQueryClient()

  return useMutation({
    mutationFn: ({
      libraryRoot,
      noteId,
    }: {
      libraryRoot: string
      noteId: string
    }) => notesDelete(libraryRoot, noteId),
    onSuccess: (_data, variables) => {
      void qc.invalidateQueries({
        queryKey: queryKeys.notes.list(variables.libraryRoot),
      })
    },
  })
}
