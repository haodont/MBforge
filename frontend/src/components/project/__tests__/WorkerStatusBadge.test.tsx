import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { WorkerStatusBadge } from '../WorkerStatusBadge'

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: () => {} },
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en' },
  }),
}))

describe('WorkerStatusBadge', () => {
  it.each([
    ['online', 'queue.workerOnline'],
    ['offline', 'queue.workerOffline'],
    ['unknown', 'queue.workerUnknown'],
  ] as const)('renders %s status label', (status, label) => {
    render(<WorkerStatusBadge status={status} />)
    expect(screen.getByText(label)).toBeInTheDocument()
  })
})
