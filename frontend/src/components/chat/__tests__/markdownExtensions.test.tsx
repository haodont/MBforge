import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MermaidAwareCodeBlock } from '../markdownExtensions'

vi.mock('../../ui/MermaidCode', () => ({
  MermaidCode: ({ code }: { code: string }) => <div data-testid="mermaid">{code}</div>
}))

describe('MermaidAwareCodeBlock', () => {
  it('renders molecode blocks as Mermaid and extracts page metadata', async () => {
    const onClick = vi.fn()
    render(
      <MermaidAwareCodeBlock className="language-molecode" onMoleculeClick={onClick}>
        {`%% page=3\nsubgraph M\nend`}
      </MermaidAwareCodeBlock>
    )
    await waitFor(() => {
      expect(screen.getByTestId('mermaid').textContent).toContain('%% page=3')
    })
    fireEvent.click(screen.getByTestId('mermaid'))
    expect(onClick).toHaveBeenCalledWith({ page: 3 })
  })
})
