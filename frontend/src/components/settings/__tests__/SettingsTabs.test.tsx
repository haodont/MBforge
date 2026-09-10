import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { DEFAULT_SETTINGS } from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@/components/ui/ScrollColumn', () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))

vi.mock('@/components/settings/GeneralTab', () => ({
  default: () => <div>general-tab</div>,
}))
vi.mock('@/components/settings/PdfProcessingTab', () => ({
  default: () => <div>pdf-processing-tab</div>,
}))
vi.mock('@/components/settings/ModelsAndEnvironmentSection', () => ({
  default: ({ libraryRoot }: { libraryRoot: string }) => (
    <div>models-env:{libraryRoot}</div>
  ),
}))
vi.mock('@/components/settings/AboutTab', () => ({
  default: () => <div>about-tab</div>,
}))

import SettingsTabs from '../SettingsTabs'

function makeProps(overrides: Partial<React.ComponentProps<typeof SettingsTabs>> = {}) {
  return {
    settings: DEFAULT_SETTINGS,
    setSettings: vi.fn(),
    libraryRoot: 'C:/lib',
    onReset: vi.fn(),
    onOpenConfig: vi.fn(),
    ...overrides,
  }
}

describe('SettingsTabs', () => {
  it('shows the general tab by default', () => {
    render(<SettingsTabs {...makeProps()} />)

    expect(screen.getByText('general-tab')).toBeTruthy()
    expect(screen.queryByText('pdf-processing-tab')).toBeNull()
    expect(screen.queryByText('about-tab')).toBeNull()
  })

  it('switches to pdf_processing tab on click', () => {
    render(<SettingsTabs {...makeProps()} />)

    fireEvent.click(screen.getByRole('tab', { name: 'settings.tabs.pdfProcessing' }))

    expect(screen.getByText('pdf-processing-tab')).toBeTruthy()
    expect(screen.queryByText('general-tab')).toBeNull()
  })

  it('switches to models_environment tab and passes libraryRoot only', () => {
    render(<SettingsTabs {...makeProps({ libraryRoot: 'C:/mylib' })} />)

    fireEvent.click(screen.getByRole('tab', { name: 'settings.tabs.modelsEnvironment' }))

    expect(screen.getByText('models-env:C:/mylib')).toBeTruthy()
    expect(screen.queryByText('general-tab')).toBeNull()
  })

  it('switches to about tab on click', () => {
    render(<SettingsTabs {...makeProps()} />)

    fireEvent.click(screen.getByRole('tab', { name: 'settings.tabs.about' }))

    expect(screen.getByText('about-tab')).toBeTruthy()
    expect(screen.queryByText('general-tab')).toBeNull()
  })
})
