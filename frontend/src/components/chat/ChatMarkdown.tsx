import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { renderInlineLatex } from './chatUtils'
import { MermaidAwareCodeBlock } from './markdownExtensions'

interface ChatMarkdownProps {
  content: string
  onDocumentLink?: (docId: string, page?: number) => void
  onMoleculeLink?: (molId: string) => void
}

export default function ChatMarkdown({ content, onDocumentLink, onMoleculeLink }: ChatMarkdownProps) {
  return (
    <div className="chat-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => {
            const processed = renderInlineLatex(children)
            return <p>{processed}</p>
          },
          h1: ({ children }) => <h1>{renderInlineLatex(children)}</h1>,
          h2: ({ children }) => <h2>{renderInlineLatex(children)}</h2>,
          h3: ({ children }) => <h3>{renderInlineLatex(children)}</h3>,
          li: ({ children }) => <li>{renderInlineLatex(children)}</li>,
          a: ({ node: _node, ...props }) => {
            const source = /^#document\/([a-f0-9]{64})(?:\?page=([1-9]\d*))?$/i.exec(props.href ?? '')
            if (source && onDocumentLink) return <a {...props} onClick={event => {
              event.preventDefault()
              onDocumentLink(source[1], source[2] ? Number(source[2]) : undefined)
            }} />
            const molecule = /^#molecule\/([a-z0-9_-]{1,128})$/i.exec(props.href ?? '')
            if (molecule && onMoleculeLink) return <a {...props} onClick={event => {
              event.preventDefault()
              onMoleculeLink(molecule[1])
            }} />
            return <a {...props} target="_blank" rel="noopener noreferrer" />
          },
          img: ({ node: _node, ...props }) => (
            <img
              {...props}
              alt={props.alt || ''}
              loading="lazy"
              decoding="async"
              onClick={() => props.src && window.open(props.src, '_blank', 'noopener,noreferrer')}
            />
          ),
          code: props => <MermaidAwareCodeBlock {...props} />,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}
