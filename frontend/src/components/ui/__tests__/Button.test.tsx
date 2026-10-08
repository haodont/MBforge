import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import Button from '../Button'

describe('Button', () => {
  it('calls onClick when clicked', () => {
    const onClick = vi.fn()
    render(<Button onClick={onClick}>Click</Button>)
    fireEvent.click(screen.getByText('Click'))
    expect(onClick).toHaveBeenCalledOnce()
  })

  it('is disabled when disabled prop is true', () => {
    const onClick = vi.fn()
    render(<Button disabled onClick={onClick}>Click</Button>)
    const btn = screen.getByText('Click').closest('button')
    expect(btn).toBeDisabled()
    fireEvent.click(btn as HTMLElement)
    expect(onClick).not.toHaveBeenCalled()
  })

  it('renders icon alongside children', () => {
    render(<Button icon={<span data-testid="icon">🔍</span>}>Search</Button>)
    expect(screen.getByTestId('icon')).toBeInTheDocument()
    expect(screen.getByText('Search')).toBeInTheDocument()
  })
})
