import { memo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import 'katex/dist/katex.min.css'
import { useDocumentMarkdown } from '@/api/query/hooks'
import { MermaidAwareCodeBlock } from '@/components/chat/markdownExtensions'
import { renderInlineLatex } from '@/components/chat/chatUtils'
import Spinner from '@/components/ui/Spinner'
import { cleanMoleculePlaceholders, rewriteImageUrls } from './markdownUtils'

interface MarkdownPaneProps {
  docId: string
  libraryRoot: string
  onMoleculeClick?: (info: { page: number }) => void
  embedded?: boolean
}

const MarkdownPane = memo(function MarkdownPane({
  docId,
  libraryRoot,
  onMoleculeClick,
  embedded = false,
}: MarkdownPaneProps) {
  const { data, isLoading } = useDocumentMarkdown(docId, libraryRoot)
  const result = data
  const error = result && !result.ok ? result.error : null
  const md = result && result.ok ? result.text : null

  if (error) {
    return (
      <div style={{ padding: 16, color: 'var(--danger)' }}>
        Failed to load document Markdown: {error}
      </div>
    )
  }
  if (isLoading || md === null) {
    return (
      <div style={{ padding: 32, textAlign: 'center' }}>
        <Spinner /> Loading…
      </div>
    )
  }

  const cleanedMarkdown = rewriteImageUrls(
    cleanMoleculePlaceholders(md),
    docId,
    libraryRoot
  )

  return (
    <div className="markdown-pane markdown-preview" style={{ padding: '16px 24px', overflow: embedded ? 'visible' : 'auto' }}>
      {cleanedMarkdown ? (
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            p: ({ children }) => <p>{renderInlineLatex(children)}</p>,
            li: ({ children }) => <li>{renderInlineLatex(children)}</li>,
            td: ({ children }) => <td>{renderInlineLatex(children)}</td>,
            th: ({ children }) => <th>{renderInlineLatex(children)}</th>,
            code: props => (
              <MermaidAwareCodeBlock
                {...props}
                onMoleculeClick={onMoleculeClick}
              />
            ),
            img: ({ node: _node, ...props }) => (
              <img
                {...props}
                alt={props.alt || ''}
                style={{ maxWidth: '100%' }}
              />
            ),
          }}
        >
          {cleanedMarkdown}
        </ReactMarkdown>
      ) : (
        <div className="markdown-pane__empty">暂无可展示的 Markdown 内容</div>
      )}
    </div>
  )
})

export default MarkdownPane
