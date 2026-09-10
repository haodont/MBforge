import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { QueryClientProvider } from '@tanstack/react-query'
import { createQueryClient } from '@/api/query/client'

vi.mock('react-i18next', () => {
  const t = (key: string) => key
  return { useTranslation: () => ({ t }) }
})

vi.mock('@/hooks/useToast', () => ({ showToast: vi.fn() }))

const mockSetTheme = vi.fn()
vi.mock('@/hooks/useTheme', () => ({ useTheme: () => ({ setTheme: mockSetTheme }) }))
vi.mock('@/i18n', () => ({ default: { changeLanguage: vi.fn() } }))

vi.mock('@/context/AppContext', () => ({
  useAppContext: () => ({ libraryRoot: 'C:/lib' }),
}))

vi.mock('@/api/http/settings', () => ({
  getSettings: vi.fn(),
  saveSettings: vi.fn(),
  getConfigDir: vi.fn(),
}))

vi.mock('@/components/ui/PageContainer', () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))
vi.mock('@/components/ui/PageTitle', () => ({
  default: ({ children }: { children: React.ReactNode }) => <h1>{children}</h1>,
}))
vi.mock('@/components/ui/AlertBanner', () => ({
  default: ({ message, onDismiss }: { message: string; onDismiss?: () => void }) => (
    <div role="alert">
      {message}
      {onDismiss && <button onClick={onDismiss}>dismiss</button>}
    </div>
  ),
}))
vi.mock('@/components/ui/Button', () => ({
  default: ({
    children,
    onClick,
    disabled,
    loading,
  }: {
    children: React.ReactNode
    onClick?: () => void
    disabled?: boolean
    loading?: boolean
  }) => (
    <button onClick={onClick} disabled={disabled ?? loading}>
      {children}
    </button>
  ),
}))

vi.mock('@/components/settings/SettingsTabs', () => ({
  default: ({
    settings,
    setSettings,
  }: {
    settings: { theme: string }
    setSettings: (fn: (s: { theme: string }) => { theme: string }) => void
  }) => (
    <div>
      <span data-testid="current-theme">{settings.theme}</span>
      <button
        onClick={() =>
          setSettings((s) => ({ ...s, theme: s.theme === 'dark' ? 'light' : 'dark' }))
        }
      >
        toggle-theme
      </button>
    </div>
  ),
}))

import { getSettings, saveSettings } from '@/api/http/settings'
import SettingsPage from '../SettingsPage'

const LOADED_SETTINGS = {
  general: { theme: 'dark', language: 'en' },
  llm: {
    provider: '',
    base_url: '',
    api_key: '',
    model: '',
    max_tokens: 4096,
    temperature: 0.7,
    top_p: 1.0,
    request_timeout: 60,
    language: 'en',
  },
  vlm: { provider: '', base_url: '', api_key: '', model: '' },
  ocr: {
    priority: [],
    provider: '',
    base_url: '',
    api_key: '',
    model: '',
    use_hf_mirror: false,
    use_pdf_inspector: false,
    paddleocr_api_key: null,
    paddleocr_host: null,
    paddleocr_model: null,
  },
  model_server: { host: '127.0.0.1', port: 18791, auto_start: true, startup_timeout: 30 },
  pipeline: {
    batch_size: 16,
    moldet_confidence_threshold: 0.5,
    max_molecules_per_page: 50,
  },
}

describe('SettingsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getSettings).mockResolvedValue({ success: true, settings: LOADED_SETTINGS })
    vi.mocked(saveSettings).mockResolvedValue({ success: true })
  })

  function renderPage() {
    const client = createQueryClient()
    return render(
      <QueryClientProvider client={client}>
        <SettingsPage />
      </QueryClientProvider>,
    )
  }

  it('Save button is disabled when settings are not dirty', async () => {
    renderPage()

    const saveBtn = await screen.findByRole('button', { name: 'common.save' })
    expect(saveBtn).toBeDisabled()
  })

  it('Save button becomes enabled after a setting change', async () => {
    renderPage()

    const saveBtn = await screen.findByRole('button', { name: 'common.save' })
    expect(saveBtn).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: 'toggle-theme' }))

    await waitFor(() => expect(saveBtn).not.toBeDisabled())
  })

  it('Cancel reverts settings to the loaded state', async () => {
    renderPage()

    await screen.findByRole('button', { name: 'common.save' })

    fireEvent.click(screen.getByRole('button', { name: 'toggle-theme' }))
    await waitFor(() => expect(screen.getByTestId('current-theme').textContent).toBe('light'))

    fireEvent.click(screen.getByRole('button', { name: 'common.cancel' }))

    expect(screen.getByTestId('current-theme').textContent).toBe('dark')
    const saveBtn = screen.getByRole('button', { name: 'common.save' })
    expect(saveBtn).toBeDisabled()
  })

  it('Save calls saveSettings and clears dirty state on success', async () => {
    renderPage()

    const saveBtn = await screen.findByRole('button', { name: 'common.save' })

    fireEvent.click(screen.getByRole('button', { name: 'toggle-theme' }))
    await waitFor(() => expect(saveBtn).not.toBeDisabled())
    fireEvent.click(saveBtn)

    await waitFor(() => expect(saveSettings).toHaveBeenCalledOnce())

    await waitFor(() => {
      return saveBtn.hasAttribute('disabled')
    })
  })

  it('shows an error banner when loading fails', async () => {
    vi.mocked(getSettings).mockResolvedValue({ success: false, error: 'db error' })

    renderPage()

    await waitFor(() => {
      const alert = screen.getByRole('alert')
      expect(alert.textContent).toContain('db error')
    })
  })

  it('shows an error banner when saving fails', async () => {
    vi.mocked(saveSettings).mockResolvedValue({ success: false, error: 'write failed' })

    renderPage()

    const saveBtn = await screen.findByRole('button', { name: 'common.save' })

    fireEvent.click(screen.getByRole('button', { name: 'toggle-theme' }))
    await waitFor(() => expect(saveBtn).not.toBeDisabled())
    fireEvent.click(saveBtn)

    await waitFor(() => {
      const alert = screen.getByRole('alert')
      expect(alert.textContent).toContain('write failed')
    })
  })
})
