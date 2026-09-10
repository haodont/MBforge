import { describe, it, expect, vi } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import { MermaidCode } from '../MermaidCode'

vi.mock('mermaid', () => ({
  default: {
    initialize: vi.fn(),
    render: vi.fn((_id: string, code: string) => {
      // Simulate rendered SVG with a malicious script tag.
      const sanitizedHint = code.includes('<script>') ? '' : code
      return Promise.resolve({
        svg: `<svg><text>${sanitizedHint}</text><script>alert('xss')</script></svg>`,
      })
    }),
  },
}))

describe('MermaidCode', () => {
  it('sanitizes rendered SVG before injecting it', async () => {
    render(<MermaidCode code="graph TD; A-->B" />)
    await waitFor(() => expect(document.querySelector('svg')).toBeInTheDocument())
    expect(document.querySelector('script')).not.toBeInTheDocument()
  })
})
