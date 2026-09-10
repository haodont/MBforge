import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'
import { useDocsIndex, useDocsPage } from '@/api/query/hooks'
import type { DocPageSummary } from '@/api/http/docs'
import { MermaidAwareCodeBlock } from './chat/markdownExtensions'
import { FileTextIcon, RefreshCwIcon } from './icons'
import IconButton from './ui/IconButton'
import './wiki.css'
import { getUserFacingError } from '@/utils/errors'

function pageSlug(value: string | undefined, pages: DocPageSummary[]): string {
  if (value && pages.some(page => page.slug === value)) return value
  return pages[0]?.slug ?? 'readme'
}

export default function Wiki() {
  const navigate = useNavigate()
  const { slug } = useParams<{ slug?: string }>()
  const [isIndexOpen, setIsIndexOpen] = useState(false)

  const indexQuery = useDocsIndex()
  const pages = useMemo(() => indexQuery.data?.pages ?? [], [indexQuery.data])
  const selectedSlug = useMemo(() => pageSlug(slug, pages), [pages, slug])
  const pageQuery = useDocsPage(selectedSlug)

  const content = pageQuery.data?.content ?? ''
  const activeSlug = pageQuery.data?.slug ?? ''
  const isLoading = indexQuery.isLoading || pageQuery.isLoading
  const error =
    indexQuery.error ? getUserFacingError(indexQuery.error)
    : pageQuery.error ? getUserFacingError(pageQuery.error)
    : null

  // Keep the URL in sync: when the index loads and the current slug is not a
  // real page, redirect to the first page (replacing history).
  useEffect(() => {
    if (pages.length === 0) return
    const resolved = pageSlug(slug, pages)
    if (!slug || slug !== resolved) {
      void navigate(`/docs/${resolved}`, { replace: true })
    }
  }, [pages, slug, navigate])

  const selectPage = (nextSlug: string) => {
    setIsIndexOpen(false)
    void navigate(`/docs/${nextSlug}`)
  }

  return (
    <div className="wiki-page">
      <aside className={`wiki-index${isIndexOpen ? ' is-open' : ''}`}>
        <div className="wiki-index__header">
          <div>
            <span className="wiki-eyebrow">MBForge</span>
            <h1>开发 Wiki</h1>
          </div>
          <IconButton
            size={36}
            className="wiki-index__close"
            ariaLabel="关闭目录"
            onClick={() => setIsIndexOpen(false)}
          >
            <span aria-hidden="true">×</span>
          </IconButton>
        </div>
        <p className="wiki-index__description">架构、运行方式、数据契约与长期开发规则。</p>
        <nav className="wiki-index__nav" aria-label="Wiki 页面">
          {pages.map(page => (
            <button
              type="button"
              key={page.slug}
              className={`wiki-index__item${page.slug === activeSlug ? ' is-active' : ''}`}
              onClick={() => selectPage(page.slug)}
            >
              <FileTextIcon size={16} />
              <span>{page.title}</span>
            </button>
          ))}
        </nav>
      </aside>

      <section className="wiki-content">
        <div className="wiki-toolbar">
          <button type="button" className="wiki-mobile-index" onClick={() => setIsIndexOpen(true)}>
            <FileTextIcon size={16} />
            目录
          </button>
          <div className="wiki-breadcrumb">
            <span>docs/pages</span>
            <span aria-hidden="true">/</span>
            <strong>{activeSlug || 'readme'}.md</strong>
          </div>
          <div className="wiki-toolbar__actions">
            <IconButton
              size={36}
              ariaLabel="刷新 Wiki"
              title="刷新 Wiki"
              onClick={() => window.location.reload()}
            >
              <RefreshCwIcon size={16} />
            </IconButton>
          </div>
        </div>

        <main className="wiki-article-wrap">
          {isLoading && !content ? (
            <div className="wiki-state">加载 Wiki…</div>
          ) : error ? (
            <div className="wiki-state wiki-state--error">{error}</div>
          ) : (
            <article className="wiki-article">
              <div className="wiki-article__meta">长期开发文档</div>
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[rehypeRaw]}
                components={{ code: MermaidAwareCodeBlock as never }}
              >
                {content}
              </ReactMarkdown>
            </article>
          )}
        </main>
      </section>
    </div>
  )
}
