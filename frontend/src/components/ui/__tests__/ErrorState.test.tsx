import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ErrorState } from '../ErrorState'

describe('ErrorState', () => {
  it('renders string error message', () => {
    render(<ErrorState error="Something went wrong" />)
    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
  })

  it('renders Error object message', () => {
    render(<ErrorState error={new Error('Network failure')} />)
    expect(screen.getByText('Network failure')).toBeInTheDocument()
  })

  it('renders retry button and calls onRetry', () => {
    const onRetry = vi.fn()
    render(<ErrorState error="Failed" onRetry={onRetry} />)
    const btn = screen.getByText('Retry')
    fireEvent.click(btn)
    expect(onRetry).toHaveBeenCalledOnce()
  })

  it('renders dismiss button and calls onDismiss', () => {
    const onDismiss = vi.fn()
    render(<ErrorState error="Failed" onDismiss={onDismiss} />)
    const btn = screen.getByText('Dismiss')
    fireEvent.click(btn)
    expect(onDismiss).toHaveBeenCalledOnce()
  })

  it('renders compact variant', () => {
    const { container } = render(<ErrorState error="Compact error" compact />)
    expect(container.firstChild).toHaveClass('error-state--compact')
  })
})
