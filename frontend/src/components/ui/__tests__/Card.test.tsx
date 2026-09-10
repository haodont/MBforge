import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import Card from '../Card'

describe('Card', () => {
  it('renders children', () => {
    render(<Card><span data-testid="child">content</span></Card>)
    expect(screen.getByTestId('child')).toBeInTheDocument()
  })

  it('renders plain div when not hoverable and no onClick', () => {
    const { container } = render(<Card>plain</Card>)
    const el = container.firstChild
    expect(el?.nodeName).toBe('DIV')
    expect(el).not.toHaveClass('motion-div')
  })

  it('calls onClick when clicked', () => {
    const onClick = vi.fn()
    render(<Card onClick={onClick}>click</Card>)
    fireEvent.click(screen.getByText('click'))
    expect(onClick).toHaveBeenCalledOnce()
  })
})
