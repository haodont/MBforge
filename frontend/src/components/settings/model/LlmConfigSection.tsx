import { useTranslation } from 'react-i18next'
import SettingSection, { SettingGroup, SettingItem } from '@/components/ui/SettingSection'
import { NumberField, ProviderField, SelectField } from '../SettingRow'
import { ModelSelector } from '../ModelComponents'
import {
  LLM_MODELS,
  getProviderMeta,
  providerOptions,
} from '../modelConfigs'
import type { SettingsState } from '../types'

interface Props {
  settings: SettingsState
  setSettings: React.Dispatch<React.SetStateAction<SettingsState>>
  markDirty: (field: string) => void
  dirtyFields: Record<string, boolean>
}

export default function LlmConfigSection({
  settings,
  setSettings,
  markDirty,
  dirtyFields,
}: Props) {
  const { t } = useTranslation()
  const update = <K extends keyof SettingsState>(key: K, value: SettingsState[K]) => {
    setSettings(s => ({ ...s, [key]: value }))
  }

  return (
    <SettingSection>
      <SettingGroup title={t('settings.connectionGroup')}>
        <ProviderField
          label={t('settings.llmProvider')}
          description={t('settings.llmProviderDesc')}
          provider={settings.llm_provider}
          onProviderChange={v => {
            markDirty('llm_provider')
            update('llm_provider', v)
          }}
          baseUrl={settings.llm_base_url}
          onBaseUrlChange={v => { markDirty('llm_base_url'); update('llm_base_url', v) }}
          apiKey={settings.llm_api_key}
          onApiKeyChange={v => { markDirty('llm_api_key'); update('llm_api_key', v) }}
          providerOptions={providerOptions(LLM_MODELS, t)}
          needsKey={getProviderMeta(settings.llm_provider).needsKey}
          baseUrlPlaceholder={getProviderMeta(settings.llm_provider).defaultUrl}
          baseUrlLabel={t('settings.llmBaseUrl')}
          apiKeyLabel={t('settings.llmApiKey')}
          dirty={dirtyFields.llm_provider}
          baseUrlDirty={dirtyFields.llm_base_url}
          apiKeyDirty={dirtyFields.llm_api_key}
        />
        <SettingItem title={t('settings.llmModel')} layout="stacked" dirty={dirtyFields.llm_model}>
          <ModelSelector
            provider={settings.llm_provider}
            modelValue={settings.llm_model}
            models={{ [settings.llm_provider]: LLM_MODELS[settings.llm_provider] ?? [] }}
            onChange={v => { markDirty('llm_model'); update('llm_model', v) }}
          />
        </SettingItem>
      </SettingGroup>

      <SettingGroup title={t('settings.llmSampling')}>
        <NumberField
          label={t('settings.maxTokens')}
          description={t('settings.maxTokensDesc')}
          value={settings.llm_max_tokens}
          onChange={v => { markDirty('llm_max_tokens'); update('llm_max_tokens', v) }}
          min={1}
          max={65536}
          step={128}
          width={120}
          dirty={dirtyFields.llm_max_tokens}
        />
        <NumberField
          label={t('settings.temperature')}
          description={t('settings.temperatureDesc')}
          value={settings.llm_temperature}
          onChange={v => { markDirty('llm_temperature'); update('llm_temperature', v) }}
          min={0}
          max={2}
          step={0.1}
          width={100}
          dirty={dirtyFields.llm_temperature}
        />
        <NumberField
          label={t('settings.topP')}
          description={t('settings.topPDesc')}
          value={settings.llm_top_p}
          onChange={v => { markDirty('llm_top_p'); update('llm_top_p', v) }}
          min={0}
          max={1}
          step={0.05}
          width={100}
          dirty={dirtyFields.llm_top_p}
        />
        <NumberField
          label={t('settings.requestTimeout')}
          description={t('settings.requestTimeoutDesc')}
          value={settings.llm_request_timeout}
          onChange={v => { markDirty('llm_request_timeout'); update('llm_request_timeout', v) }}
          min={1}
          max={600}
          step={10}
          width={120}
          dirty={dirtyFields.llm_request_timeout}
        />
      </SettingGroup>

      <SettingGroup title={t('settings.llmAdvanced')}>
        <SelectField
          label={t('settings.llmLanguage')}
          description={t('settings.llmLanguageDesc')}
          value={settings.llm_language}
          onChange={v => { markDirty('llm_language'); update('llm_language', v) }}
          options={[
            { value: 'en', label: 'English' },
            { value: 'zh', label: '中文' },
          ]}
          dirty={dirtyFields.llm_language}
        />
      </SettingGroup>
    </SettingSection>
  )
}
