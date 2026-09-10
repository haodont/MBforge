import { useMemo, useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { PageContainer, PageTitle, Button, Input, EmptyState, AlertBanner } from './ui'
import { PlusIcon, SearchIcon } from './icons'
import NoteEditor, { type Note } from './notes/NoteEditor'
import { showToast } from '@/hooks/useToast'
import { useAppContext } from '@/context/AppContext'
import {
  useNotes,
  useNotesBacklinks,
  useSaveNote,
  useDeleteNote,
} from '@/api/query/hooks'
import { StaggerContainer, StaggerItem } from './animations/StaggerContainer'
import NoteListItem from './notes/NoteListItem'
import TagPill from './notes/TagPill'
import BacklinksPanel from './notes/BacklinksPanel'

export default function Notes() {
  const { t } = useTranslation()
  const { libraryRoot } = useAppContext()
  const [activeId, setActiveId] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [activeTag, setActiveTag] = useState<string | null>(null)

  const { data: notes = [], isLoading, isFetching } = useNotes(libraryRoot)
  const saveMutation = useSaveNote()
  const deleteMutation = useDeleteNote()
  const { data: backlinks = [] } = useNotesBacklinks(libraryRoot, activeId)

  // When the note list first arrives (or a re-fetch lands), keep the active
  // selection valid by defaulting to the first note.
  useEffect(() => {
    if (notes.length === 0) return
    if (!activeId || !notes.some(n => n.id === activeId)) {
      setActiveId(notes[0].id)
    }
  }, [notes, activeId])

  const activeNote = useMemo(
    () => notes.find(n => n.id === activeId) ?? null,
    [notes, activeId],
  )

  const filteredNotes = useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    if (!q) return notes
    return notes.filter(n =>
      n.title.toLowerCase().includes(q) ||
      n.content.toLowerCase().includes(q) ||
      n.tags.some(t => t.toLowerCase().includes(q)),
    )
  }, [notes, searchQuery])

  const allTags = useMemo(() => {
    const set = new Set<string>()
    notes.forEach(n => n.tags.forEach(t => set.add(t)))
    return Array.from(set)
  }, [notes])

  const tagFiltered = useMemo(() => {
    if (!activeTag) return filteredNotes
    return filteredNotes.filter(n => n.tags.includes(activeTag))
  }, [filteredNotes, activeTag])

  const handleCreate = async () => {
    if (!libraryRoot) return
    const newNote: Note = {
      id: `note_${Date.now()}`,
      title: t('notes.create'),
      content: '',
      tags: [],
      links: [],
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    }
    try {
      const saved = await saveMutation.mutateAsync({ libraryRoot, note: newNote })
      setActiveId(saved.id)
      showToast(t('notes.created'), 'success')
    } catch {
      showToast(t('notes.saveFailed'), 'error')
    }
  }

  const handleWikiLinkClick = (title: string) => {
    const target = notes.find(
      n => n.title.trim().toLowerCase() === title.trim().toLowerCase(),
    )
    if (target) {
      setActiveId(target.id)
      showToast(t('notes.jumped', { title: target.title }), 'info')
    } else {
      showToast(t('notes.notFound', { title }), 'warning')
    }
  }

  const wikilinkSuggestions = useMemo(
    () =>
      notes.map(n => ({
        id: n.id,
        title: n.title || '(无标题)',
        type: 'note' as const,
      })),
    [notes],
  )

  const handleUpdate = async (updated: Note) => {
    if (!libraryRoot) return
    try {
      await saveMutation.mutateAsync({ libraryRoot, note: updated })
    } catch (error) {
      showToast(t('notes.saveFailed'), 'error')
      throw error
    }
  }

  const handleDelete = async (id: string) => {
    if (!libraryRoot) return
    try {
      await deleteMutation.mutateAsync({ libraryRoot, noteId: id })
      if (activeId === id) {
        setActiveId(notes.find(n => n.id !== id)?.id ?? null)
      }
      showToast(t('notes.deleted'), 'success')
    } catch {
      showToast(t('notes.deleteFailed'), 'error')
    }
  }

  return (
    <PageContainer>
      <div className="notes-header">
        <div>
          <PageTitle>{t('notes.title')}</PageTitle>
          <div className="notes-header-subtitle">
            {t('notes.subtitle', { count: notes.length })}
          </div>
          {(isLoading || isFetching) && <div className="notes-header-status">{t('notes.loading')}</div>}
          {!libraryRoot && (
            <div className="notes-header-status notes-header-status--warn">
              {t('notes.noProject')}
            </div>
          )}
        </div>
        <Button variant="primary" onClick={handleCreate}>
          <PlusIcon size={14} /> {t('notes.create')}
        </Button>
      </div>

      <AlertBanner variant="info" message={t('notes.banner')} />

      <div className="notes-layout">
        {/* 左侧：笔记列表 */}
        <div className="notes-sidebar">
          <div className="notes-search-wrap">
            <span className="notes-search-icon">
              <SearchIcon size={14} />
            </span>
            <Input
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              placeholder={t('notes.searchPlaceholder')}
              className="notes-search-input"
            />
          </div>

          {allTags.length > 0 && (
            <div className="notes-tags-row">
              <TagPill
                label={t('notes.allTags')}
                active={activeTag === null}
                onClick={() => setActiveTag(null)}
              />
              {allTags.map(tag => (
                <TagPill
                  key={tag}
                  label={tag}
                  active={activeTag === tag}
                  onClick={() => setActiveTag(activeTag === tag ? null : tag)}
                />
              ))}
            </div>
          )}

          {tagFiltered.length === 0 ? (
            <EmptyState message={t('notes.empty')} />
          ) : (
            <StaggerContainer stagger={0.04}>
              <div className="notes-list">
                {tagFiltered.map(note => (
                  <StaggerItem key={note.id}>
                    <NoteListItem
                      note={note}
                      active={activeId === note.id}
                      onClick={() => setActiveId(note.id)}
                    />
                  </StaggerItem>
                ))}
              </div>
            </StaggerContainer>
          )}
        </div>

        {/* 右侧：编辑器 + 反向链接 */}
        <div className="notes-main">
          <NoteEditor
            note={activeNote}
            onChange={handleUpdate}
            onDelete={handleDelete}
            wikilinkSuggestions={wikilinkSuggestions}
            onWikiLinkClick={handleWikiLinkClick}
          />
          <BacklinksPanel backlinks={backlinks} onJump={handleWikiLinkClick} />
        </div>
      </div>
    </PageContainer>
  )
}
