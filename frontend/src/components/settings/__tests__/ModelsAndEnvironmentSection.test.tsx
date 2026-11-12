import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { DEFAULT_SETTINGS } from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@/components/settings/ModelsTab', () => ({
  default: () => <div>models-tab</div>,
}))

vi.mock('@/components/settings/ReadinessTab', () => ({
  default: ({ libraryRoot }: { libraryRoot: string }) => <div>readiness:{libraryRoot}</div>,
}))

import ModelsAndEnvironmentSection from '../ModelsAndEnvironmentSection'

describe('ModelsAndEnvironmentSection', () => {
  it('mounts the models tab by default and switches to the readiness tab', () => {
    render(
      <ModelsAndEnvironmentSection
        settings={DEFAULT_SETTINGS}
        setSettings={vi.fn()}
        libraryRoot="C:/lib"
      />,
    )

    expect(screen.getByText('models-tab')).toBeTruthy()
    expect(screen.queryByText('readiness:C:/lib')).toBeNull()

    fireEvent.click(screen.getByRole('tab', { name: 'settings.tabs.readiness' }))
    expect(screen.getByText('readiness:C:/lib')).toBeTruthy()
    expect(screen.queryByText('models-tab')).toBeNull()
  })
})
