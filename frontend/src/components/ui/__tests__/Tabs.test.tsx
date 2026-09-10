import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import Tabs, { TabPanel } from '../Tabs'
import type { TabItem } from '../Tabs'

const defaultItems: TabItem[] = [
  { key: 'tab1', label: 'Tab One' },
  { key: 'tab2', label: 'Tab Two' },
  { key: 'tab3', label: 'Tab Three', disabled: true },
]

describe('Tabs', () => {
  it('renders all tab items', () => {
    render(<Tabs items={defaultItems} />)
    expect(screen.getByText('Tab One')).toBeInTheDocument()
    expect(screen.getByText('Tab Two')).toBeInTheDocument()
    expect(screen.getByText('Tab Three')).toBeInTheDocument()
  })

  it('activates first tab by default in uncontrolled mode', () => {
    render(<Tabs items={defaultItems} />)
    const tab1 = screen.getByText('Tab One').closest('button')
    const tab2 = screen.getByText('Tab Two').closest('button')
    expect(tab1).toHaveClass('ui-tabs__tab--active')
    expect(tab2).not.toHaveClass('ui-tabs__tab--active')
  })

  it('switches active tab on click in uncontrolled mode', () => {
    const onChange = vi.fn()
    render(<Tabs items={defaultItems} onChange={onChange} />)
    fireEvent.click(screen.getByText('Tab Two'))
    expect(onChange).toHaveBeenCalledWith('tab2')
  })

  it('respects defaultActiveKey', () => {
    render(<Tabs items={defaultItems} defaultActiveKey="tab2" />)
    const tab2 = screen.getByText('Tab Two').closest('button')
    expect(tab2).toHaveClass('ui-tabs__tab--active')
  })

  it('works in controlled mode with activeKey', () => {
    render(<Tabs items={defaultItems} activeKey="tab2" />)
    const tab2 = screen.getByText('Tab Two').closest('button')
    expect(tab2).toHaveClass('ui-tabs__tab--active')
  })

  it('calls onChange in controlled mode', () => {
    const onChange = vi.fn()
    render(<Tabs items={defaultItems} activeKey="tab1" onChange={onChange} />)
    fireEvent.click(screen.getByText('Tab Two'))
    expect(onChange).toHaveBeenCalledWith('tab2')
  })

  it('does not switch on disabled tab click', () => {
    const onChange = vi.fn()
    render(<Tabs items={defaultItems} onChange={onChange} />)
    const tab3 = screen.getByText('Tab Three').closest('button')
    expect(tab3).toBeDisabled()
    fireEvent.click(tab3 as Element)
    expect(onChange).not.toHaveBeenCalled()
  })

  it('renders badge on tab', () => {
    const items: TabItem[] = [
      { key: 'a', label: 'Inbox', badge: 5 },
      { key: 'b', label: 'Sent' },
    ]
    render(<Tabs items={items} />)
    expect(screen.getByText('5')).toBeInTheDocument()
  })

  it('wires ARIA ids when id prop is provided', () => {
    render(<Tabs items={defaultItems} id="settings" />)
    const tab1 = screen.getByText('Tab One').closest('button')
    const tab2 = screen.getByText('Tab Two').closest('button')
    expect(tab1).toHaveAttribute('id', 'settings-tab1-tab')
    expect(tab1).toHaveAttribute('aria-controls', 'settings-tab1-panel')
    expect(tab2).toHaveAttribute('id', 'settings-tab2-tab')
    expect(tab2).toHaveAttribute('aria-controls', 'settings-tab2-panel')
  })
})

describe('TabPanel', () => {
  it('renders children when activeKey matches tabKey', () => {
    render(<TabPanel activeKey="tab1" tabKey="tab1"><span>Content</span></TabPanel>)
    expect(screen.getByText('Content')).toBeInTheDocument()
  })

  it('renders nothing when activeKey does not match tabKey', () => {
    const { container } = render(<TabPanel activeKey="tab2" tabKey="tab1"><span>Content</span></TabPanel>)
    expect(container.querySelector('div')).toBeNull()
  })

  it('renders with role tabpanel', () => {
    render(<TabPanel activeKey="a" tabKey="a">Panel</TabPanel>)
    expect(screen.getByRole('tabpanel')).toBeInTheDocument()
  })

  it('forceMount keeps DOM even when inactive', () => {
    const { container } = render(
      <TabPanel activeKey="tab2" tabKey="tab1" forceMount><span>Hidden</span></TabPanel>
    )
    expect(screen.getByText('Hidden')).toBeInTheDocument()
    expect(container.querySelector('[role="tabpanel"]')).toBeInTheDocument()
  })

  it('wires ARIA ids when tabsId prop is provided', () => {
    render(<TabPanel activeKey="tab1" tabKey="tab1" tabsId="settings">Panel</TabPanel>)
    const panel = screen.getByRole('tabpanel')
    expect(panel).toHaveAttribute('id', 'settings-tab1-panel')
    expect(panel).toHaveAttribute('aria-labelledby', 'settings-tab1-tab')
  })
})
