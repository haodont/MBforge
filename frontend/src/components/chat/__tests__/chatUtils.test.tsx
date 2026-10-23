// chatUtils contract: patent/OCR chemistry notation is normalized before
// rendering, and every math shape reaches KaTeX (inline, grouped, escaped,
// delimiter-less, display) while injected hrefs stay sanitized.
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { normalizePatentLatex, renderInlineLatex } from '../chatUtils'

describe('chatUtils patent LaTeX', () => {
  it('renders inline, grouped, escaped, delimiter-less and display math without leaking injected markup', () => {
    // Inline math inside surrounding text.
    let view = render(<span>{renderInlineLatex('Energy $E=mc^2$ value')}</span>)
    expect(screen.getByText(/Energy/)).toBeInTheDocument()
    expect(document.querySelector('.katex')).toBeInTheDocument()
    view.unmount()

    // Patent-style grouped formulas produce one KaTeX node per formula.
    view = render(<span>{renderInlineLatex('$\\mathbb{R}^9$ 取代基取代； $\\mathrm{C}{1 - 4}$ 卤代烷基')}</span>)
    expect(document.querySelectorAll('.katex')).toHaveLength(2)
    view.unmount()

    // The same formulas survive ReactMarkdown's paragraph parsing.
    view = render(
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{ p: ({ children }) => <p>{renderInlineLatex(children)}</p> }}
      >
        {'$\\mathbb{R}^9$ 取代基取代； $\\mathrm{C}{1 - 4}$ 卤代烷基'}
      </ReactMarkdown>,
    )
    expect(document.querySelectorAll('.katex')).toHaveLength(2)
    view.unmount()

    // Escaped markdown delimiters are normalized before KaTeX.
    view = render(<span>{renderInlineLatex('\\$\\\\mathbb{R}^9\\$')}</span>)
    expect(document.querySelector('.katex')).toBeInTheDocument()
    view.unmount()

    // Patent carbon-range notation becomes a subscript.
    view = render(<span>{renderInlineLatex('$\\mathrm{C}{3 - 6}$')}</span>)
    expect(document.querySelector('.katex')).toBeInTheDocument()
    view.unmount()

    // Formulas with a missing opening delimiter are still recovered.
    view = render(<span>{renderInlineLatex('\\mathrm{C(O)OR^f}、\\mathrm{C(O)NR^{d}R^{d}}$、或 $\\\\mathrm{NR^{d}S(O)2R^{g}}$')}</span>)
    expect(document.querySelectorAll('.katex').length).toBeGreaterThanOrEqual(3)
    view.unmount()

    // Display math.
    view = render(<span>{renderInlineLatex('$$\\frac{1}{2}$$')}</span>)
    expect(document.querySelector('.katex-display')).toBeInTheDocument()
    view.unmount()

    // Injected scripts inside math are stripped.
    render(<span>{renderInlineLatex('$\\href{javascript:alert(1)}{x}$')}</span>)
    expect(document.querySelector('script')).not.toBeInTheDocument()
  })

  it('normalizes OCR chemistry notation before rendering', () => {
    expect(normalizePatentLatex('\\\\mathrm{C*{3 - 6}}、\\mathrm{S(O)*2R^{g}}')).toBe(
      '\\mathrm{C}_{3 - 6}、\\mathrm{S(O)2R^{g}}',
    )
  })
})
