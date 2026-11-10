// Settings surface usage tests.
//
// Covers `SettingsPage` (load → edit → cancel/save lifecycle and the
// load/save failure banners), the top-level tab routing of `SettingsTabs`
// through the real page (each tab leaf stubbed, models tab scoped to the
// library root), and the `SettingsState` ↔ backend payload contract owned by
// `settings/types.ts` (flattenSettings / toBackendPayload / isSettingsEqual).
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
  useAppContext: () => ({ libraryRoot: 'C:/mylib' }),
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
vi.mock('@/components/ui/ScrollColumn', () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))

// Tab leaves are stubbed; the general tab doubles as the dirty-state toggle so
// the page lifecycle can be driven without depending on a real settings form.
vi.mock('@/components/settings/GeneralTab', () => ({
  default: ({
    settings,
    setSettings,
  }: {
    settings: SettingsState
    setSettings: (update: (state: SettingsState) => SettingsState) => void
  }) => (
    <div>
      general-tab
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
vi.mock('@/components/settings/PdfProcessingTab', () => ({
  default: () => <div>pdf-processing-tab</div>,
}))
vi.mock('@/components/settings/ModelsAndEnvironmentSection', () => ({
  default: ({ libraryRoot }: { libraryRoot: string }) => <div>models-env:{libraryRoot}</div>,
}))
vi.mock('@/components/settings/AboutTab', () => ({
  default: () => <div>about-tab</div>,
}))

import { getSettings, saveSettings } from '@/api/http/settings'
import SettingsPage from '../SettingsPage'
import {
  flattenSettings,
  isSettingsEqual,
  toBackendPayload,
  type SettingsState,
} from '../types'

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
  layout: {
    conf_threshold: 0.4,
    cross_model: true,
    max_pages_per_doc: null,
  },
  model_server: { host: '127.0.0.1', port: 18791, auto_start: true, startup_timeout: 30 },
  pipeline: {
    batch_size: 16,
    moldet_confidence_threshold: 0.5,
    max_molecules_per_page: 50,
  },
}

function renderPage() {
  const client = createQueryClient()
  return render(
    <QueryClientProvider client={client}>
      <SettingsPage />
    </QueryClientProvider>,
  )
}

describe('SettingsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getSettings).mockResolvedValue({ success: true, settings: LOADED_SETTINGS })
    vi.mocked(saveSettings).mockResolvedValue({ success: true })
  })

  it('gates Save on dirtiness, reverts on Cancel and persists through saveSettings', async () => {
    renderPage()

    const saveBtn = await screen.findByRole('button', { name: 'common.save' })
    expect(saveBtn).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: 'toggle-theme' }))
    await waitFor(() => expect(saveBtn).not.toBeDisabled())

    // Cancel restores the loaded state and clears dirtiness.
    fireEvent.click(screen.getByRole('button', { name: 'common.cancel' }))
    expect(screen.getByTestId('current-theme').textContent).toBe('dark')
    expect(saveBtn).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: 'toggle-theme' }))
    await waitFor(() => expect(saveBtn).not.toBeDisabled())
    fireEvent.click(saveBtn)

    await waitFor(() => expect(saveSettings).toHaveBeenCalledOnce())
    await waitFor(() => expect(saveBtn).toBeDisabled())
  })

  it('surfaces load and save failures in the alert banner', async () => {
    vi.mocked(getSettings).mockResolvedValue({ success: false, error: 'db error' })
    const failedLoad = renderPage()
    await waitFor(() => {
      expect(screen.getByRole('alert').textContent).toContain('db error')
    })
    failedLoad.unmount()

    vi.mocked(getSettings).mockResolvedValue({ success: true, settings: LOADED_SETTINGS })
    vi.mocked(saveSettings).mockResolvedValue({ success: false, error: 'write failed' })
    renderPage()

    const saveBtn = await screen.findByRole('button', { name: 'common.save' })
    fireEvent.click(screen.getByRole('button', { name: 'toggle-theme' }))
    await waitFor(() => expect(saveBtn).not.toBeDisabled())
    fireEvent.click(saveBtn)

    await waitFor(() => {
      expect(screen.getByRole('alert').textContent).toContain('write failed')
    })
  })

  it('routes between the settings tabs and scopes the models tab to the library root', async () => {
    renderPage()
    await screen.findByRole('button', { name: 'common.save' })

    expect(screen.getByText('general-tab')).toBeTruthy()
    expect(screen.queryByText('pdf-processing-tab')).toBeNull()
    expect(screen.queryByText('about-tab')).toBeNull()

    fireEvent.click(screen.getByRole('tab', { name: 'settings.tabs.pdfProcessing' }))
    expect(screen.getByText('pdf-processing-tab')).toBeTruthy()
    expect(screen.queryByText('general-tab')).toBeNull()

    fireEvent.click(screen.getByRole('tab', { name: 'settings.tabs.modelsEnvironment' }))
    expect(screen.getByText('models-env:C:/mylib')).toBeTruthy()
    expect(screen.queryByText('general-tab')).toBeNull()

    fireEvent.click(screen.getByRole('tab', { name: 'settings.tabs.about' }))
    expect(screen.getByText('about-tab')).toBeTruthy()
    expect(screen.queryByText('general-tab')).toBeNull()
  })
})

describe('settings payload contract', () => {
  it('round-trips layout and model-cache settings through the backend payload', () => {
    // Saved layout parameters round-trip through the staged state.
    const layout = flattenSettings({
      layout: { conf_threshold: 0.55, cross_model: false },
    })
    expect(layout.layout_conf_threshold).toBe(0.55)
    expect(layout.layout_cross_model).toBe(false)
    expect(toBackendPayload(layout).layout).toEqual({
      conf_threshold: 0.55,
      cross_model: false,
    })

    // Producer defaults apply when the backend omits layout.
    const defaults = flattenSettings({})
    expect(defaults.layout_conf_threshold).toBe(0.4)
    expect(defaults.layout_cross_model).toBe(true)

    // Model cache path changes are detected and forwarded.
    const cache = flattenSettings({ model_cache_dir: 'C:/models' })
    const changed = { ...cache, model_cache_dir: 'D:/mbforge-cache' }
    expect(isSettingsEqual(cache, changed)).toBe(false)
    expect(toBackendPayload(changed).model_cache_dir).toBe('D:/mbforge-cache')
  })
})
