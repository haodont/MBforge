import type { ChangeEvent, KeyboardEvent } from 'react'
import type { NoteLink } from './types'

export interface EditViewProps {
  draftContent: string
  onContentChange: (e: ChangeEvent<HTMLTextAreaElement>) => void
  onKeyDown: (e: KeyboardEvent<HTMLTextAreaElement>) => void
  showSuggestions: boolean
  wikilinkSuggestions: Array<{ id: string; title: string; type: NoteLink['type'] }>
  onSelectSuggestion: (title: string) => void
}

/**
 * 编辑模式视图.
 *
 * - 渲染 <textarea>
 * - 监听 [[ 输入触发 wikilink suggestion 浮层
 * - 监听 Ctrl/Cmd+S 快捷键保存
 */
export default function EditView({
  draftContent,
  onContentChange,
  onKeyDown,
  showSuggestions,
  wikilinkSuggestions,
  onSelectSuggestion,
}: EditViewProps) {
  return (
    <div style={{ position: 'relative' }}>
      <textarea
        id="note-content-textarea"
        value={draftContent}
        onChange={onContentChange}
        onKeyDown={onKeyDown}
        placeholder="开始记录…"
        style={{
          width: '100%',
          minHeight: 300,
          padding: '14px 16px',
          fontSize: 14,
          lineHeight: 1.7,
          background: 'transparent',
          border: 'none',
          color: 'var(--text-primary)',
          fontFamily: 'inherit',
          resize: 'vertical',
          outline: 'none',
        }}
      />
      {showSuggestions && wikilinkSuggestions.length > 0 && (
        <div
          style={{
            position: 'absolute',
            top: 8,
            right: 16,
            background: 'var(--bg-surface)',
            border: '1px solid var(--border)',
            borderRadius: 6,
            boxShadow: '0 4px 12px rgba(0,0,0,0.1)',
            maxHeight: 240,
            overflowY: 'auto',
            minWidth: 200,
            zIndex: 10,
          }}
        >
          {wikilinkSuggestions.slice(0, 8).map(s => (
            <button
              key={s.id}
              type="button"
              onClick={() => onSelectSuggestion(s.title)}
              style={{
                display: 'block',
                width: '100%',
                textAlign: 'left',
                padding: '8px 12px',
                background: 'transparent',
                border: 'none',
                fontSize: 12,
                color: 'var(--text-primary)',
                cursor: 'pointer',
              }}
              onMouseEnter={e => {
                e.currentTarget.style.background = 'var(--bg-hover)'
              }}
              onMouseLeave={e => {
                e.currentTarget.style.background = 'transparent'
              }}
            >
              <code style={{ fontFamily: 'monospace' }}>[[{s.title}]]</code>
              <span style={{ marginLeft: 8, color: 'var(--text-muted)', fontSize: 10 }}>
                {s.type}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
