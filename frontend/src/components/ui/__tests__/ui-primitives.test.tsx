/**
 * Shared UI primitive contracts (src/components/ui):
 * Chip, Button, Card, EmptyState, ErrorState, LoadingState, Panel,
 * Tabs + TabPanel, ConfirmDialog, Menu.
 *
 * One test per component contract: selection/collapse/ARIA state machines,
 * click dispatch and disabled/loading guards. Pure prop forwarding
 * ("renders children"/"renders icon") is intentionally not asserted.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import Chip from '../Chip'
import Button from '../Button'
import Card from '../Card'
import EmptyState from '../EmptyState'
import { ErrorState } from '../ErrorState'
import { LoadingState } from '../LoadingState'
import { Panel } from '../Panel'
import Tabs, { TabPanel } from '../Tabs'
import type { TabItem } from '../Tabs'
import ConfirmDialog from '../ConfirmDialog'
import Menu from '../Menu'

const defaultItems: TabItem[] = [
  { key: 'tab1', label: 'Tab One' },
  { key: 'tab2', label: 'Tab Two' },
  { key: 'tab3', label: 'Tab Three', disabled: true },
]

describe('Chip', () => {
  it('shows label/count/active state and reports clicks', () => {
    const onClick = vi.fn()
    render(<Chip label="Pending" count={3} active onClick={onClick} />)
    expect(screen.getByText('Pending')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
    const chip = screen.getByRole('button', { name: /pending/i })
    expect(chip).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(chip)
    expect(onClick).toHaveBeenCalledOnce()
  })
})

describe('Button', () => {
  it('fires onClick when enabled and blocks it while disabled', () => {
    const onClick = vi.fn()
    const { rerender } = render(<Button onClick={onClick}>Click</Button>)
    fireEvent.click(screen.getByText('Click'))
    expect(onClick).toHaveBeenCalledOnce()

    rerender(<Button disabled onClick={onClick}>Click</Button>)
    const disabled = screen.getByText('Click').closest('button') as HTMLButtonElement
    expect(disabled).toBeDisabled()
    fireEvent.click(disabled)
    expect(onClick).toHaveBeenCalledOnce()
  })
})

describe('Card', () => {
  it('renders its children and forwards clicks', () => {
    const onClick = vi.fn()
    render(<Card onClick={onClick}><span data-testid="child">content</span></Card>)
    expect(screen.getByTestId('child')).toBeInTheDocument()
    fireEvent.click(screen.getByText('content'))
    expect(onClick).toHaveBeenCalledOnce()
  })
})

describe('EmptyState', () => {
  it('renders message/icon and fires the action callback', () => {
    const onClick = vi.fn()
    render(<EmptyState message="Add items" icon={<span data-testid="icon">🔍</span>} action={{ label: 'Add', onClick }} />)
    expect(screen.getByText('Add items')).toBeInTheDocument()
    expect(screen.getByTestId('icon')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Add'))
    expect(onClick).toHaveBeenCalledOnce()
  })
})

describe('ErrorState', () => {
  it('renders string/Error messages and wires retry + dismiss', () => {
    const onRetry = vi.fn()
    const onDismiss = vi.fn()
    const { unmount } = render(<ErrorState error="Something went wrong" onRetry={onRetry} onDismiss={onDismiss} />)
    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Retry'))
    expect(onRetry).toHaveBeenCalledOnce()
    fireEvent.click(screen.getByText('Dismiss'))
    expect(onDismiss).toHaveBeenCalledOnce()
    unmount()

    render(<ErrorState error={new Error('Network failure')} />)
    expect(screen.getByText('Network failure')).toBeInTheDocument()
  })
})

describe('LoadingState', () => {
  it('renders the message of every variant', () => {
    const cases = [
      { props: { variant: 'spinner', message: 'Loading...' } as const, text: 'Loading...' },
      { props: { variant: 'progress', progress: 65, progressLabel: 'Indexing...' } as const, text: 'Indexing...' },
      { props: { message: 'Please wait' } as const, text: 'Please wait' },
    ]
    for (const c of cases) {
      const { unmount } = render(<LoadingState {...c.props} />)
      expect(screen.getByText(c.text), JSON.stringify(c.props)).toBeInTheDocument()
      unmount()
    }
  })
})

describe('Panel', () => {
  it('renders header/actions/footer and collapses the body', () => {
    const { unmount } = render(
      <Panel title="My Panel" collapsible actions={<button type="button">action</button>} footer={<span>footer</span>}>
        <span>body</span>
      </Panel>,
    )
    expect(screen.getByText('My Panel')).toBeInTheDocument()
    expect(screen.getByText('body')).toBeInTheDocument()
    expect(screen.getByText('footer')).toBeInTheDocument()
    expect(screen.getByText('action')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { expanded: true }))
    expect(screen.queryByText('body')).not.toBeInTheDocument()
    unmount()

    render(<Panel title="C" collapsible defaultCollapsed><span>body</span></Panel>)
    expect(screen.queryByText('body')).not.toBeInTheDocument()
  })
})

describe('Tabs', () => {
  it('selects the first tab by default and switches on click in uncontrolled mode', () => {
    const onChange = vi.fn()
    const first = render(<Tabs items={defaultItems} onChange={onChange} />)
    expect(screen.getByText('Tab One')).toBeInTheDocument()
    expect(screen.getByText('Tab Two')).toBeInTheDocument()
    expect(screen.getByText('Tab Three')).toBeInTheDocument()
    expect(screen.getByRole('tab', { selected: true })).toHaveTextContent('Tab One')
    fireEvent.click(screen.getByText('Tab Two'))
    expect(onChange).toHaveBeenCalledWith('tab2')
    first.unmount()

    const second = render(<Tabs items={defaultItems} defaultActiveKey="tab2" />)
    expect(screen.getByRole('tab', { selected: true })).toHaveTextContent('Tab Two')
    second.unmount()

    render(<Tabs items={[{ key: 'a', label: 'Inbox', badge: 5 }, { key: 'b', label: 'Sent' }]} />)
    expect(screen.getByText('5')).toBeInTheDocument()
  })

  it('honours controlled selection, blocks disabled tabs, and wires ARIA ids', () => {
    const onChange = vi.fn()
    render(<Tabs items={defaultItems} activeKey="tab2" onChange={onChange} id="settings" />)
    expect(screen.getByRole('tab', { selected: true })).toHaveTextContent('Tab Two')

    const tab1 = screen.getByText('Tab One').closest('button') as HTMLButtonElement
    const tab2 = screen.getByText('Tab Two').closest('button') as HTMLButtonElement
    expect(tab1).toHaveAttribute('id', 'settings-tab1-tab')
    expect(tab1).toHaveAttribute('aria-controls', 'settings-tab1-panel')
    expect(tab2).toHaveAttribute('id', 'settings-tab2-tab')
    expect(tab2).toHaveAttribute('aria-controls', 'settings-tab2-panel')

    fireEvent.click(tab1)
    expect(onChange).toHaveBeenCalledWith('tab1')
    expect(screen.getByRole('tab', { selected: true })).toHaveTextContent('Tab Two')

    const tab3 = screen.getByText('Tab Three').closest('button') as HTMLButtonElement
    expect(tab3).toBeDisabled()
    fireEvent.click(tab3)
    expect(onChange).toHaveBeenCalledOnce()
  })

  it('closes a closable tab without selecting it', () => {
    const onChange = vi.fn()
    const onTabClose = vi.fn()
    render(
      <Tabs
        items={[
          { key: 'a', label: 'Alpha' },
          { key: 'b', label: 'Beta', closable: true },
        ]}
        activeKey="a"
        onChange={onChange}
        onTabClose={onTabClose}
        closeLabel="Close tab"
      />,
    )
    const close = screen.getByRole('button', { name: 'Close tab: Beta' })
    fireEvent.click(close)
    expect(onTabClose).toHaveBeenCalledWith('b')
    expect(onChange).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: 'Close tab: Alpha' })).not.toBeInTheDocument()
  })
})

describe('TabPanel', () => {
  it('mounts only the active panel, honours forceMount, and wires ARIA ids', () => {
    const active = render(<TabPanel activeKey="tab1" tabKey="tab1" tabsId="settings"><span>Content</span></TabPanel>)
    const panel = screen.getByRole('tabpanel')
    expect(panel).toHaveTextContent('Content')
    expect(panel).toHaveAttribute('id', 'settings-tab1-panel')
    expect(panel).toHaveAttribute('aria-labelledby', 'settings-tab1-tab')
    active.unmount()

    const inactive = render(<TabPanel activeKey="tab2" tabKey="tab1"><span>Content</span></TabPanel>)
    expect(screen.queryByRole('tabpanel')).not.toBeInTheDocument()
    inactive.unmount()

    render(<TabPanel activeKey="tab2" tabKey="tab1" forceMount><span>Hidden</span></TabPanel>)
    expect(screen.getByText('Hidden')).toBeInTheDocument()
    expect(screen.getByRole('tabpanel')).toBeInTheDocument()
  })
})

describe('ConfirmDialog', () => {
  it('renders when open, fires onConfirm, and blocks confirm while loading', () => {
    const onConfirm = vi.fn()
    const onCancel = vi.fn()
    const { rerender } = render(
      <ConfirmDialog open title="Delete doc" message="Really?" confirmLabel="Delete" onConfirm={onConfirm} onCancel={onCancel} />,
    )
    expect(screen.getByText('Delete doc')).toBeInTheDocument()
    expect(screen.getByText('Really?')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(onConfirm).toHaveBeenCalledOnce()
    expect(onCancel).not.toHaveBeenCalled()

    rerender(<ConfirmDialog open={false} title="Hidden" onConfirm={onConfirm} onCancel={onCancel} />)
    expect(screen.queryByText('Hidden')).not.toBeInTheDocument()

    rerender(<ConfirmDialog open title="Busy" confirmLabel="Delete" loading onConfirm={onConfirm} onCancel={onCancel} />)
    expect(screen.getByRole('button', { name: 'Delete' })).toBeDisabled()
  })
})

describe('Menu', () => {
  it('opens from the trigger, fires item callbacks and closes on selection', async () => {
    const onDelete = vi.fn()
    const onPick = vi.fn()
    render(
      <Menu
        trigger={open => <Button onClick={open}>Open</Button>}
        items={[
          { key: 'del', label: 'Delete', danger: true, onClick: onDelete },
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
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Open' }))
    expect(screen.getByRole('menu')).toBeInTheDocument()
    expect(screen.getByRole('separator')).toBeInTheDocument()
    expect(screen.getByText('Move to')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('menuitem', { name: 'Delete' }))
    expect(onDelete).toHaveBeenCalledOnce()
    await waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'Open' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Group A' }))
    expect(onPick).toHaveBeenCalledOnce()
  })
})
