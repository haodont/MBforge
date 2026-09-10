import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { DEFAULT_SETTINGS } from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@/components/settings/ModelsTab', () => ({
  default: () => <div>models-tab</div>,
}))

vi.mock('@/components/settings/ModelServiceSection', () => ({
  default: () => <div>model-service-tab</div>,
}))

vi.mock('@/components/settings/ReadinessTab', () => ({
  default: ({ libraryRoot }: { libraryRoot: string }) => <div>readiness:{libraryRoot}</div>,
}))

import ModelsAndEnvironmentSection from '../ModelsAndEnvironmentSection'

describe('ModelsAndEnvironmentSection', () => {
  it('mounts the models tab by default', () => {
    render(
      <ModelsAndEnvironmentSection
        settings={DEFAULT_SETTINGS}
        setSettings={vi.fn()}
        libraryRoot="C:/lib"
      />,
    )

    expect(screen.getByText('models-tab')).toBeTruthy()
    expect(screen.queryByText('readiness:C:/lib')).toBeNull()
  })

  it('switches to the model service tab', () => {
    render(
      <ModelsAndEnvironmentSection
        settings={DEFAULT_SETTINGS}
        setSettings={vi.fn()}
        libraryRoot="C:/lib"
      />,
    )

    fireEvent.click(screen.getByRole('tab', { name: 'settings.tabs.modelService' }))

    expect(screen.getByText('model-service-tab')).toBeTruthy()
    expect(screen.queryByText('models-tab')).toBeNull()
  })

  it('switches to the readiness tab', () => {
    render(
      <ModelsAndEnvironmentSection
        settings={DEFAULT_SETTINGS}
        setSettings={vi.fn()}
        libraryRoot="C:/lib"
      />,
    )

    fireEvent.click(screen.getByRole('tab', { name: 'settings.tabs.readiness' }))

    expect(screen.getByText('readiness:C:/lib')).toBeTruthy()
    expect(screen.queryByText('models-tab')).toBeNull()
  })
})
