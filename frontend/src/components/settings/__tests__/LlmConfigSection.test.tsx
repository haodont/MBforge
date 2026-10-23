import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClientProvider } from '@tanstack/react-query'
import { createQueryClient } from '@/api/query/client'
import { DEFAULT_SETTINGS } from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
  // utils/errors imports @/i18n which calls i18n.use(initReactI18next)
  initReactI18next: { type: '3rdParty', init: () => {} },
}))

const { fetchLlmModelsMock } = vi.hoisted(() => ({ fetchLlmModelsMock: vi.fn() }))

import type * as SettingsHttp from '@/api/http/settings'

vi.mock('@/api/http/settings', async importOriginal => {
  const actual = await importOriginal<typeof SettingsHttp>()
  return { ...actual, fetchLlmModels: fetchLlmModelsMock }
})

import LlmConfigSection from '../model/LlmConfigSection'

const renderSection = () => {
  const client = createQueryClient()
  return render(
    <QueryClientProvider client={client}>
      <LlmConfigSection
        settings={DEFAULT_SETTINGS}
        setSettings={vi.fn()}
        markDirty={vi.fn()}
        dirtyFields={{}}
      />
    </QueryClientProvider>,
  )
}

const datalistValues = () =>
  Array.from(document.querySelectorAll('datalist option')).map(o => (o as HTMLOptionElement).value)

describe('LlmConfigSection — fetch model list from provider', () => {
  beforeEach(() => {
    fetchLlmModelsMock.mockReset()
  })

  it('reflects the provider model-list probe in the datalist and status message', async () => {
    // Success: provider models are merged into the datalist next to the presets.
    fetchLlmModelsMock.mockResolvedValue({
      success: true,
      models: [
        { value: 'gpt-4.1', label: 'GPT-4.1' },
        { value: 'deepseek-chat', label: 'DeepSeek Chat' },
      ],
    })
    const success = renderSection()

    fireEvent.click(screen.getByRole('button', { name: 'settings.fetchModelsDesc' }))

    await waitFor(() => {
      expect(fetchLlmModelsMock).toHaveBeenCalledWith({
        provider: DEFAULT_SETTINGS.llm_provider,
        base_url: DEFAULT_SETTINGS.llm_base_url,
        api_key: DEFAULT_SETTINGS.llm_api_key,
      })
    })
    await waitFor(() => {
      expect(screen.getByText('settings.fetchModelsSuccess')).toBeTruthy()
    })

    const options = datalistValues()
    expect(options).toContain('gpt-4.1')
    expect(options).toContain('deepseek-chat')
    // preset suggestions remain as a fallback
    expect(options).toContain('gpt-4o')
    success.unmount()

    // Provider error: the section reports the failure instead of models.
    fetchLlmModelsMock.mockResolvedValue({
      success: false,
      error: 'authentication failed (HTTP 401) - check the API key',
    })
    const failed = renderSection()

    fireEvent.click(screen.getByRole('button', { name: 'settings.fetchModelsDesc' }))
    await waitFor(() => {
      expect(screen.getByText('settings.fetchModelsError')).toBeTruthy()
    })
    failed.unmount()

    // Empty model list: the section shows the empty hint.
    fetchLlmModelsMock.mockResolvedValue({ success: true, models: [] })
    renderSection()

    fireEvent.click(screen.getByRole('button', { name: 'settings.fetchModelsDesc' }))
    await waitFor(() => {
      expect(screen.getByText('settings.fetchModelsEmpty')).toBeTruthy()
    })
  })
})
