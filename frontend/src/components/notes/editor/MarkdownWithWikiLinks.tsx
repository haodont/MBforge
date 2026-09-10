import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export interface MarkdownWithWikiLinksProps {
  content: string
  onWikiLinkClick?: (title: string) => void
  t: (key: string, options?: Record<string, unknown>) => string
}

/**
 * 带 Wiki 链接支持的 Markdown 渲染器.
 *
 * 在传给 ReactMarkdown 之前，将 `[[Title]]` 替换为 `[Title](#wiki/Title)`.
 * 自定义 `a` 组件拦截 `#wiki/` 链接，调用 onWikiLinkClick 而非实际导航.
 *
 * 自定义渲染器:统一 h1-h3 字号 + p 间距 + code 块/行内区分 + 引用样式.
 */
export default function MarkdownWithWikiLinks({
  content,
  onWikiLinkClick,
  t,
}: MarkdownWithWikiLinksProps) {
  // 先把 [[X]] 转成自定义语法，markdown 不支持
  const preprocessed = content.replace(/\[\[([^\]]+)\]\]/g, (_match: string, title: string) => {
    return `[${title}](#wiki/${encodeURIComponent(title)})`
  })

  return (
    <div>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // 自定义链接：检测 wiki 链接
          a: ({ node: _node, ...props }) => {
            const href = props.href ?? ''
            if (href.startsWith('#wiki/')) {
              const title = decodeURIComponent(href.slice(6))
              return (
                <a
                  href={href}
                  onClick={e => {
                    e.preventDefault()
                    if (onWikiLinkClick) {
                      onWikiLinkClick(title)
                    }
                  }}
                  style={{
                    color: 'var(--accent)',
                    background: 'var(--accent-muted)',
                    padding: '1px 4px',
                    borderRadius: 3,
                    textDecoration: 'none',
                    fontSize: '0.9em',
                    cursor: onWikiLinkClick ? 'pointer' : 'help',
                  }}
                  title={
                    onWikiLinkClick
                      ? t('notes.jumpTo', { title })
                      : t('notes.unlinked', { title })
                  }
                >
                  {props.children}
                </a>
              )
            }
            return (
              <a
                {...props}
                style={{ color: 'var(--accent)' }}
                target="_blank"
                rel="noopener noreferrer"
              />
            )
          },
          h1: ({ children }) => (
            <h1 style={{ fontSize: 22, fontWeight: 600, margin: '20px 0 10px' }}>{children}</h1>
          ),
          h2: ({ children }) => (
            <h2 style={{ fontSize: 18, fontWeight: 600, margin: '18px 0 8px' }}>{children}</h2>
          ),
          h3: ({ children }) => (
            <h3 style={{ fontSize: 15, fontWeight: 600, margin: '14px 0 6px' }}>{children}</h3>
          ),
          p: ({ children }) => <p style={{ margin: '8px 0' }}>{children}</p>,
          code: ({ className, children, ...props }) => {
            const isBlock = className?.startsWith('language-')
            if (isBlock) {
              return (
                <pre
                  style={{
                    background: 'var(--bg-base)',
                    border: '1px solid var(--border)',
                    borderRadius: 6,
                    padding: '10px 12px',
                    overflowX: 'auto',
                    fontSize: 12,
                    fontFamily: 'monospace',
                  }}
                >
                  <code className={className} {...props}>
                    {children}
                  </code>
                </pre>
              )
            }
            return (
              <code
                style={{
                  background: 'var(--bg-elevated)',
                  padding: '1px 4px',
                  borderRadius: 3,
                  fontFamily: 'monospace',
                  fontSize: '0.9em',
                }}
              >
                {children}
              </code>
            )
          },
          ul: ({ children }) => <ul style={{ paddingLeft: 20, margin: '8px 0' }}>{children}</ul>,
          ol: ({ children }) => <ol style={{ paddingLeft: 20, margin: '8px 0' }}>{children}</ol>,
          blockquote: ({ children }) => (
            <blockquote
              style={{
                margin: '8px 0',
                padding: '6px 12px',
                borderLeft: '3px solid var(--accent)',
                background: 'var(--bg-base)',
                color: 'var(--text-secondary)',
              }}
            >
              {children}
            </blockquote>
          ),
        }}
      >
        {preprocessed}
      </ReactMarkdown>
    </div>
  )
}
