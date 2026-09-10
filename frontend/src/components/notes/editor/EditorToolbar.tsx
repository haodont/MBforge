import { useTranslation } from 'react-i18next'
import ToolbarButton, {
  BoldIcon,
  ItalicIcon,
  ListIcon,
  HashIcon,
  SaveIcon,
  EditorEditIcon,
  LinkIcon,
} from './ToolbarButton'

// 内联 SVG — 仅本工具栏使用
const TrashIconSvg = () => (
  <svg
    width={14}
    height={14}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth={2}
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <polyline points="3 6 5 6 21 6" />
    <path d="M19 6l-2 14a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2L5 6" />
  </svg>
)

export interface EditorToolbarProps {
  isEditing: boolean
  onBold: () => void
  onItalic: () => void
  onList: () => void
  onHeading: () => void
  onExternalLink: () => void
  onSave: () => void
  onEdit: () => void
  onDelete?: () => void
}

/**
 * 笔记编辑器顶部工具栏.
 *
 * 左侧：编辑模式下的格式化按钮 (Bold/Italic/List/Heading/Link).
 * 右侧：删除 / 编辑 / 保存切换.
 */
export default function EditorToolbar({
  isEditing,
  onBold,
  onItalic,
  onList,
  onHeading,
  onExternalLink,
  onSave,
  onEdit,
  onDelete,
}: EditorToolbarProps) {
  const { t } = useTranslation()

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '8px 12px',
        borderBottom: '1px solid var(--border)',
      }}
    >
      <div style={{ display: 'flex', gap: 4 }}>
        {isEditing && (
          <>
            <ToolbarButton onClick={onBold} title="Bold">
              <BoldIcon />
            </ToolbarButton>
            <ToolbarButton onClick={onItalic} title="Italic">
              <ItalicIcon />
            </ToolbarButton>
            <ToolbarButton onClick={onList} title="List">
              <ListIcon />
            </ToolbarButton>
            <ToolbarButton onClick={onHeading} title="Heading">
              <HashIcon />
            </ToolbarButton>
            <ToolbarButton onClick={onExternalLink} title="External link">
              <LinkIcon />
            </ToolbarButton>
          </>
        )}
      </div>
      <div style={{ display: 'flex', gap: 4 }}>
        {onDelete && !isEditing && (
          <ToolbarButton onClick={onDelete} title={t('notes.delete')}>
            <TrashIconSvg />
          </ToolbarButton>
        )}
        {isEditing ? (
          <ToolbarButton onClick={onSave} title={t('notes.save')}>
            <SaveIcon />
          </ToolbarButton>
        ) : (
          <ToolbarButton onClick={onEdit} title={t('notes.edit')}>
            <EditorEditIcon />
          </ToolbarButton>
        )}
      </div>
    </div>
  )
}
