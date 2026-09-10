import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { renderInlineLatex } from './chatUtils'
import { MermaidAwareCodeBlock } from './markdownExtensions'

interface ChatMarkdownProps {
  content: string
}

export default function ChatMarkdown({ content }: ChatMarkdownProps) {
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
          a: ({ node: _node, ...props }) => (
            <a {...props} target="_blank" rel="noopener noreferrer" />
          ),
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
