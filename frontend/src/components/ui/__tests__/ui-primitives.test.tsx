import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import Chip from '../Chip'
import ConfirmDialog from '../ConfirmDialog'
import Menu from '../Menu'
import Button from '../Button'

describe('Chip', () => {
  it('shows label and count, and reports active state', () => {
    render(<Chip label="Pending" count={3} active onClick={() => {}} />)
    expect(screen.getByText('Pending')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /pending/i })).toHaveAttribute('aria-pressed', 'true')
  })

  it('calls onClick when clicked', () => {
    const onClick = vi.fn()
    render(<Chip label="All" onClick={onClick} />)
    fireEvent.click(screen.getByRole('button', { name: /all/i }))
    expect(onClick).toHaveBeenCalledOnce()
  })
})

describe('ConfirmDialog', () => {
  it('renders title/message and fires onConfirm from the danger button', () => {
    const onConfirm = vi.fn()
    const onCancel = vi.fn()
    render(
      <ConfirmDialog open title="Delete doc" message="Really?" confirmLabel="Delete" onConfirm={onConfirm} onCancel={onCancel} />,
    )
    expect(screen.getByText('Delete doc')).toBeInTheDocument()
    expect(screen.getByText('Really?')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(onConfirm).toHaveBeenCalledOnce()
    expect(onCancel).not.toHaveBeenCalled()
  })

  it('does not render when closed', () => {
    const onCancel = vi.fn()
    render(<ConfirmDialog open={false} title="Hidden" onConfirm={() => {}} onCancel={onCancel} />)
    expect(screen.queryByText('Hidden')).not.toBeInTheDocument()
  })

  it('disables the confirm button while loading', () => {
    render(
      <ConfirmDialog open title="Busy" confirmLabel="Delete" loading onConfirm={() => {}} onCancel={() => {}} />,
    )
    expect(screen.getByRole('button', { name: 'Delete' })).toBeDisabled()
  })
})

describe('Menu', () => {
  it('opens on trigger and fires item onClick', () => {
    const onDelete = vi.fn()
    render(
      <Menu
        trigger={open => <Button onClick={open}>Open</Button>}
        items={[{ key: 'del', label: 'Delete', danger: true, onClick: onDelete }]}
      />,
    )
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Open' }))
    expect(screen.getByRole('menu')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('menuitem', { name: 'Delete' }))
    expect(onDelete).toHaveBeenCalledOnce()
  })

  it('closes the menu after an item is selected', async () => {
    render(
      <Menu
        trigger={open => <Button onClick={open}>Open</Button>}
        items={[{ key: 'a', label: 'Item A', onClick: () => {} }]}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Open' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Item A' }))
    await waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument())
  })

  it('renders separators, groups and checked items', () => {
    const onPick = vi.fn()
    render(
      <Menu
        trigger={open => <Button onClick={open}>Open</Button>}
        items={[
          { key: 'a', label: 'Top', onClick: onPick },
          { type: 'separator' },
          {
            type: 'group',
            label: 'Move to',
            items: [
              { key: 'g1', label: 'Group A', checked: true, onClick: onPick },
              { key: 'g2', label: 'Group B', onClick: onPick },
            ],
          },
        ]}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Open' }))
    expect(screen.getByRole('separator')).toBeInTheDocument()
    expect(screen.getByText('Move to')).toBeInTheDocument()
    const groupA = screen.getByRole('menuitem', { name: 'Group A' })
    expect(groupA.querySelector('.ui-menu__check')).not.toBeNull()
    fireEvent.click(groupA)
    expect(onPick).toHaveBeenCalled()
  })
})
