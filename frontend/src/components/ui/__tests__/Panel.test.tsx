import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { Panel } from '../Panel'

describe('Panel', () => {
  it('renders title and children', () => {
    render(<Panel title="My Panel"><span>content</span></Panel>)
    expect(screen.getByText('My Panel')).toBeInTheDocument()
    expect(screen.getByText('content')).toBeInTheDocument()
  })

  it('renders footer when provided', () => {
    render(<Panel title="P" footer={<span>footer</span>}><span>body</span></Panel>)
    expect(screen.getByText('footer')).toBeInTheDocument()
  })

  it('collapsible hides body on toggle', () => {
    render(<Panel title="Collapsible" collapsible><span>body</span></Panel>)
    expect(screen.getByText('body')).toBeInTheDocument()

    const btn = screen.getByRole('button', { expanded: true })
    fireEvent.click(btn)
    expect(screen.queryByText('body')).not.toBeInTheDocument()
  })

  it('defaultCollapsed starts collapsed', () => {
    render(<Panel title="C" collapsible defaultCollapsed><span>body</span></Panel>)
    expect(screen.queryByText('body')).not.toBeInTheDocument()
  })

  it('renders actions in header', () => {
    render(<Panel title="P" actions={<button type="button">action</button>}><span>body</span></Panel>)
    expect(screen.getByText('action')).toBeInTheDocument()
  })
})
