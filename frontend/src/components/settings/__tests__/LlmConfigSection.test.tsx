import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { DEFAULT_SETTINGS } from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
  // utils/errors imports @/i18n which calls i18n.use(initReactI18next)
  initReactI18next: { type: '3rdParty', init: () => {} },
}))

const { fetchLlmModelsMock } = vi.hoisted(() => ({ fetchLlmModelsMock: vi.fn() }))

vi.mock('@/api/http/settings', async importOriginal => {
  const actual = await importOriginal<typeof import('@/api/http/settings')>()
  return { ...actual, fetchLlmModels: fetchLlmModelsMock }
})

import LlmConfigSection from '../model/LlmConfigSection'

const renderSection = () => {
  render(
    <LlmConfigSection
      settings={DEFAULT_SETTINGS}
      setSettings={vi.fn()}
      markDirty={vi.fn()}
      dirtyFields={{}}
    />,
  )
}

describe('LlmConfigSection — fetch model list from provider', () => {
  beforeEach(() => {
    fetchLlmModelsMock.mockReset()
  })

  const datalistValues = () =>
    Array.from(document.querySelectorAll('datalist option')).map(o => (o as HTMLOptionElement).value)

  it('fetches the provider model list and merges it into the datalist', async () => {
    fetchLlmModelsMock.mockResolvedValue({
      success: true,
      models: [
        { value: 'gpt-4.1', label: 'GPT-4.1' },
        { value: 'deepseek-chat', label: 'DeepSeek Chat' },
      ],
    })
    renderSection()

    fireEvent.click(screen.getByRole('button', { name: 'settings.fetchModelsDesc' }))

    expect(fetchLlmModelsMock).toHaveBeenCalledWith({
      provider: DEFAULT_SETTINGS.llm_provider,
      base_url: DEFAULT_SETTINGS.llm_base_url,
      api_key: DEFAULT_SETTINGS.llm_api_key,
    })

    await waitFor(() => {
      expect(screen.getByText('settings.fetchModelsSuccess')).toBeTruthy()
    })

    const options = datalistValues()
    expect(options).toContain('gpt-4.1')
    expect(options).toContain('deepseek-chat')
    // preset suggestions remain as a fallback
    expect(options).toContain('gpt-4o')
  })

  it('shows the provider error message when the probe fails', async () => {
    fetchLlmModelsMock.mockResolvedValue({
      success: false,
      error: 'authentication failed (HTTP 401) - check the API key',
    })
    renderSection()

    fireEvent.click(screen.getByRole('button', { name: 'settings.fetchModelsDesc' }))

    await waitFor(() => {
      expect(screen.getByText('settings.fetchModelsError')).toBeTruthy()
    })
  })

  it('shows an empty hint when the provider returns no models', async () => {
    fetchLlmModelsMock.mockResolvedValue({ success: true, models: [] })
    renderSection()

    fireEvent.click(screen.getByRole('button', { name: 'settings.fetchModelsDesc' }))

    await waitFor(() => {
      expect(screen.getByText('settings.fetchModelsEmpty')).toBeTruthy()
    })
  })
})
