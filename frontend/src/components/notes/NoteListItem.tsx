import { useMemo } from 'react'
import { FlaskIcon, ClockIcon } from '../icons'
import { type Note } from './NoteEditor'
import { stripMarkdown, relativeTime } from './utils'

interface NoteListItemProps {
  note: Note
  active: boolean
  onClick: () => void
}

export default function NoteListItem({ note, active, onClick }: NoteListItemProps) {
  const excerpt = useMemo(() => {
    const text = stripMarkdown(note.content)
    return text.length > 100 ? text.slice(0, 100) + '...' : text
  }, [note.content])

  return (
    <button
      type="button"
      onClick={onClick}
      className="notes-list-item"
      data-active={active}
    >
      <div className="notes-list-item-title-row">
        <span className="notes-list-item-title" data-active={active}>
          {note.title || '(无标题)'}
        </span>
      </div>
      {excerpt && (
        <div className="notes-list-item-excerpt">{excerpt}</div>
      )}
      <div className="notes-list-item-meta">
        <div className="notes-list-item-tags">
          {note.tags.slice(0, 2).map(t => (
            <span key={t} className="notes-list-item-tag">#{t}</span>
          ))}
          {note.links.length > 0 && (
            <span className="notes-list-item-link-count">
              <FlaskIcon size={9} /> {note.links.length}
            </span>
          )}
        </div>
        <span className="notes-list-item-time">
          <ClockIcon size={9} /> {relativeTime(note.updatedAt)}
        </span>
      </div>
    </button>
  )
}
