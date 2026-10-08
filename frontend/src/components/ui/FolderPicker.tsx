import { useTranslation } from 'react-i18next'
import { useCommonDirs } from '@/api/query/hooks/useCommonDirs'
import { cleanWindowsPath } from '../../utils/path'


interface FolderPickerProps {
  value: string
  onChange: (path: string) => void
  placeholder?: string
  title?: string
  disabled?: boolean
}

export function FolderPicker({
  value,
  onChange,
  placeholder,

  disabled = false
}: FolderPickerProps) {
  const { t } = useTranslation()
  const { data: commonDirs = [] } = useCommonDirs()

  const effectivePlaceholder = placeholder ?? t('folder.select')

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(cleanWindowsPath(e.target.value))}
        placeholder={effectivePlaceholder}
        disabled={disabled}
        style={{
          width: '100%',
          height: '40px',
          padding: '0 12px',
          background: 'var(--bg-surface)',
          border: '1px solid var(--border)',
          borderRadius: '8px',
          color: 'var(--text-primary)',
          fontSize: '14px',
          outline: 'none',
          boxSizing: 'border-box',
        }}
      />
      {commonDirs.length > 0 && (
        <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
          {commonDirs.map((dir) => (
            <button
              key={dir.path}
              type="button"
              onClick={() => onChange(dir.path)}
              disabled={disabled}
              style={{
                padding: '4px 10px',
                fontSize: '12px',
                background: value === dir.path ? 'var(--accent)' : 'var(--bg-surface)',
                color: value === dir.path ? 'white' : 'var(--text-secondary)',
                border: '1px solid var(--border)',
                borderRadius: '6px',
                cursor: disabled ? 'not-allowed' : 'pointer',
              }}
            >
              {dir.name}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
