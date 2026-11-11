import { useCallback, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'
import { useDocumentMarkdown } from '@/api/query/hooks'
import Toolbar from '@/components/ui/Toolbar'
import IconButton from '@/components/ui/IconButton'
import Caption from '@/components/ui/Caption'
import { ArrowLeftIcon, HashIcon, NoteIcon } from './icons'
import { useAppContext } from '@/context/AppContext'
import { getUserFacingError } from '@/utils/errors'
import { documentLabel, shortDocId } from '@/utils/documentId'
import type { DocumentEntry } from '@/types'
import './MarkdownViewer.css'

interface Props {
  /** 项目根目录绝对路径 */
  libraryRoot: string
  /** 文档记录；标题与 PDF 跳转都从这里取 */
  doc: DocumentEntry
  /** 关闭回调 */
  onClose: () => void
}

interface MarkdownHeading {
  id: string
  level: number
  text: string
}

interface MarkdownNode {
  type?: string
  value?: string
  url?: string
  children?: MarkdownNode[]
}

/** Turn the Markdown stage's ``<!-- PAGE n -->`` comments into link nodes. */
function remarkPageLinks() {
  return (tree: MarkdownNode) => {
    const walk = (node: MarkdownNode) => {
      if (!node.children) return
      node.children = node.children.map((child) => {
        if (child.type === 'html') {
          const match = /^<!--\s*PAGE\s+(\d+)\s*-->$/i.exec((child.value ?? '').trim())
          if (match) {
            return {
              type: 'link',
              url: `#pdf-page-${match[1]}`,
              children: [{ type: 'text', value: `PAGE ${match[1]}` }],
            }
          }
        }
        walk(child)
        return child
      })
    }
    walk(tree)
  }
}

export default function MarkdownViewer({ libraryRoot, doc, onClose }: Props) {
  const { t } = useTranslation()
  const { openTab } = useAppContext()
  const [viewMode, setViewMode] = useState<'rendered' | 'source'>('rendered')

  const { data: result, isLoading } = useDocumentMarkdown(doc.doc_id, libraryRoot)
  let error: string | null = null
  if (result && !result.ok) {
    // Check if it's a "not found" error — pipeline may not have completed yet
    const isNotFound = result.error.includes('not found') || result.error.includes('404')
    if (isNotFound) {
      error = `文档 "${documentLabel(doc)}" 的 Markdown 尚未生成，请等待 pipeline 处理完成后再查看`
    } else {
      error = getUserFacingError(result.error, '加载文档内容失败')
    }
  }
  const content = result && result.ok ? result.text : ''

  const { prepared, headings } = useMemo(() => {
    const found: MarkdownHeading[] = []
    let inFence = false
    const lines: string[] = []
    for (const line of content.split('\n')) {
      if (/^\s*```/.test(line)) {
        inFence = !inFence
        lines.push(line)
        continue
      }
      if (inFence) {
        lines.push(line)
        continue
      }
      const match = /^(#{1,3})\s+(.+?)\s*$/.exec(line)
      if (!match) {
        lines.push(line)
        continue
      }
      const id = `md-heading-${found.length}`
      found.push({
        id,
        level: match[1].length,
        text: match[2].replace(/[*_`]/g, '').trim(),
      })
      lines.push(`<a id="${id}"></a>`, line)
    }
    return { prepared: lines.join('\n'), headings: found }
  }, [content])

  const openPdfPage = useCallback((page: number) => {
    openTab({
      type: 'pdf',
      title: doc.title,
      doc,
      libraryRoot,
      initialPage: page,
    })
  }, [doc, libraryRoot, openTab])

  const components = useMemo<Components>(() => ({
    a: ({ href, children }) => {
      const pageMatch = /^#pdf-page-(\d+)$/.exec(href ?? '')
      if (pageMatch) {
        return (
          <button
            type="button"
            className="markdown-page-link"
            onClick={() => openPdfPage(Number(pageMatch[1]))}
          >
            {t('md.openPdfPage', { page: pageMatch[1] })}
          </button>
        )
      }
      return <a href={href}>{children}</a>
    },
  }), [openPdfPage, t])

  return (
    <div className="markdown-viewer">
      <Toolbar className="markdown-viewer__toolbar">
        <IconButton size={40} onClick={onClose} ariaLabel={t('common.close')}>
          <ArrowLeftIcon size={18} />
        </IconButton>
        <Caption truncate className="markdown-viewer__title">
          {doc.title || shortDocId(doc.doc_id)}
        </Caption>

        <div className="markdown-viewer__mode">
          <button
            type="button"
            className={`markdown-viewer__mode-button${viewMode === 'rendered' ? ' is-active' : ''}`}
            onClick={() => setViewMode('rendered')}
            title={t('md.preview')}
          >
            <NoteIcon size={11} /> {t('md.preview')}
          </button>
          <button
            type="button"
            className={`markdown-viewer__mode-button${viewMode === 'source' ? ' is-active' : ''}`}
            onClick={() => setViewMode('source')}
            title={t('md.source')}
          >
            <HashIcon size={11} /> {t('md.source')}
          </button>
        </div>
      </Toolbar>

      <div className="markdown-viewer__body">
        {viewMode === 'rendered' && headings.length > 0 && (
          <nav className="markdown-toc" aria-label={t('md.toc')}>
            <div className="markdown-toc__title">{t('md.toc')}</div>
            {headings.map(heading => (
              <button
                key={heading.id}
                type="button"
                className={`markdown-toc__item markdown-toc__item--level-${heading.level}`}
                onClick={() => document.getElementById(heading.id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
              >
                {heading.text}
              </button>
            ))}
          </nav>
        )}

        <div className="markdown-viewer__document">
          {isLoading ? (
            <div className="markdown-viewer__state">{t('common.loading')}</div>
          ) : error ? (
            <div className="markdown-viewer__state markdown-viewer__state--error">{error}</div>
          ) : viewMode === 'rendered' ? (
            <div className="markdown-preview">
              <ReactMarkdown
                remarkPlugins={[remarkGfm, remarkPageLinks]}
                rehypePlugins={[rehypeRaw]}
                components={components}
              >
                {prepared}
              </ReactMarkdown>
            </div>
          ) : (
            <pre className="markdown-viewer__source">{content}</pre>
          )}
        </div>
      </div>
    </div>
  )
}
