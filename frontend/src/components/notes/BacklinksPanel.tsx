import { Card, Badge } from '../ui'
import { type Note } from './NoteEditor'
import { relativeTime } from './utils'

interface BacklinksPanelProps {
  backlinks: Note[]
  onJump: (title: string) => void
}

export default function BacklinksPanel({ backlinks, onJump }: BacklinksPanelProps) {
  if (backlinks.length === 0) return null
  return (
    <Card padding="14px">
      <div className="notes-backlinks-header">
        <h4 className="notes-backlinks-title">反向链接</h4>
        <Badge variant="neutral">{backlinks.length} 条</Badge>
      </div>
      <div className="notes-backlinks-list">
        {backlinks.map(n => (
          <button
            key={n.id}
            type="button"
            onClick={() => onJump(n.title)}
            className="notes-backlink-item"
          >
            <span className="notes-backlink-title">{n.title || '(无标题)'}</span>
            <span className="notes-backlink-time">{relativeTime(n.updatedAt)}</span>
          </button>
        ))}
      </div>
    </Card>
  )
}
