import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'
import { useDocumentMarkdown } from '@/api/query/hooks'
import Toolbar from '@/components/ui/Toolbar'
import IconButton from '@/components/ui/IconButton'
import Caption from '@/components/ui/Caption'
import { ArrowLeftIcon, HashIcon, NoteIcon } from './icons'
import { getUserFacingError } from '@/utils/errors'

interface Props {
  /** 项目根目录绝对路径 */
  libraryRoot: string
  /** 文档 ID（经正式 document artifact 路由解析内容） */
  docId: string
  /** 关闭回调 */
  onClose: () => void
}

export default function MarkdownViewer({ libraryRoot, docId, onClose }: Props) {
  const { t } = useTranslation()
  const [viewMode, setViewMode] = useState<'rendered' | 'source'>('rendered')

  const { data: result, isLoading } = useDocumentMarkdown(docId, libraryRoot)
  let error: string | null = null
  if (result && !result.ok) {
    // Check if it's a "not found" error — pipeline may not have completed yet
    const isNotFound = result.error.includes('not found') || result.error.includes('404')
    if (isNotFound) {
      error = `文档 "${docId}" 的 Markdown 尚未生成，请等待 pipeline 处理完成后再查看`
    } else {
      error = getUserFacingError(result.error, '加载文档内容失败')
    }
  }
  const content = result && result.ok ? result.text : ''

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      {/* 工具栏 */}
      <Toolbar style={{ justifyContent: 'flex-start', gap: '12px', height: '48px', padding: '0 16px' }}>
        <IconButton size={40} onClick={onClose}>
          <ArrowLeftIcon size={18} />
        </IconButton>
        <Caption truncate style={{ fontSize: '13px', fontWeight: 500, flex: 1 }}>
          {docId}
        </Caption>

        {/* 渲染 / 源码 切换 */}
        <div style={{
          display: 'flex',
          gap: '2px',
          background: 'var(--bg-base)',
          borderRadius: '6px',
          padding: '2px',
        }}>
          <button
            onClick={() => setViewMode('rendered')}
            style={{
              padding: '4px 10px',
              fontSize: '11px',
              borderRadius: '4px',
              border: 'none',
              background: viewMode === 'rendered' ? 'var(--bg-surface)' : 'transparent',
              color: viewMode === 'rendered' ? 'var(--text-primary)' : 'var(--text-muted)',
              cursor: 'pointer',
              fontWeight: viewMode === 'rendered' ? 600 : 400,
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
            }}
            title={t('md.preview')}
          >
            <NoteIcon size={11} /> {t('md.preview')}
          </button>
          <button
            onClick={() => setViewMode('source')}
            style={{
              padding: '4px 10px',
              fontSize: '11px',
              borderRadius: '4px',
              border: 'none',
              background: viewMode === 'source' ? 'var(--bg-surface)' : 'transparent',
              color: viewMode === 'source' ? 'var(--text-primary)' : 'var(--text-muted)',
              cursor: 'pointer',
              fontWeight: viewMode === 'source' ? 600 : 400,
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
            }}
            title={t('md.source')}
          >
            <HashIcon size={11} /> {t('md.source')}
          </button>
        </div>
      </Toolbar>

      {/* Markdown 内容 */}
      <div style={{
        flex: 1,
        overflow: 'auto',
        padding: '24px 32px',
        maxWidth: '900px',
        margin: '0 auto',
        width: '100%',
      }}>
        {isLoading ? (
          <div style={{
            textAlign: 'center', padding: '40px',
            color: 'var(--text-muted)', fontSize: '13px',
          }}>
            {t('common.loading')}
          </div>
        ) : error ? (
          <div style={{
            textAlign: 'center', padding: '40px',
            color: 'var(--danger)', fontSize: '13px',
          }}>
            {error}
          </div>
        ) : viewMode === 'rendered' ? (
          <div className="markdown-preview">
            <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>
              {content}
            </ReactMarkdown>
          </div>
        ) : (
          <pre style={{
            fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
            fontSize: '12px',
            lineHeight: 1.6,
            color: 'var(--text-secondary)',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
          }}>
            {content}
          </pre>
        )}
      </div>
    </div>
  )
}
