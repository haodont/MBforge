// VLM config section — provider/model wiring (vision-language model,
// simpler than LLM).
//
// `ModelConfigCard` injects the shared `settings` / `setSettings` / `markDirty` /
// `dirtyFields`; this component only renders the modelType='vlm' groups.

import { useTranslation } from 'react-i18next'
import SettingSection, { SettingGroup, SettingItem } from '@/components/ui/SettingSection'
import { ProviderField } from '../SettingRow'
import { ModelSelector } from '../ModelComponents'
import {
  PROVIDER_META,
  VLM_MODELS,
  type ModelMap,
} from '../modelConfigs'
import type { SettingsState } from '../types'

interface Props {
  settings: SettingsState
  setSettings: React.Dispatch<React.SetStateAction<SettingsState>>
  markDirty: (field: string) => void
  dirtyFields: Record<string, boolean>
}

const providerOptions = (map: ModelMap, t: (key: string, options?: Record<string, unknown>) => string) =>
  Object.keys(map).map(k => ({
    value: k,
    label: t(`providers.${k}`, { defaultValue: (PROVIDER_META[k] ?? { label: k }).label }),
  }))

const getProviderMeta = (key: string) =>
  PROVIDER_META[key] ?? { label: key, defaultUrl: '', needsKey: false }

export default function VlmConfigSection({
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
          label={t('settings.vlmProvider')}
          description={t('settings.vlmProviderDesc')}
          provider={settings.vlm_provider}
          onProviderChange={v => { markDirty('vlm_provider'); update('vlm_provider', v) }}
          baseUrl={settings.vlm_base_url}
          onBaseUrlChange={v => { markDirty('vlm_base_url'); update('vlm_base_url', v) }}
          apiKey={settings.vlm_api_key}
          onApiKeyChange={v => { markDirty('vlm_api_key'); update('vlm_api_key', v) }}
          providerOptions={providerOptions(VLM_MODELS, t)}
          needsKey={getProviderMeta(settings.vlm_provider).needsKey}
          baseUrlPlaceholder={getProviderMeta(settings.vlm_provider).defaultUrl}
          dirty={dirtyFields.vlm_provider}
          baseUrlDirty={dirtyFields.vlm_base_url}
          apiKeyDirty={dirtyFields.vlm_api_key}
        />
        <SettingItem title={t('settings.model')} layout="stacked" dirty={dirtyFields.vlm_model}>
          <ModelSelector
            provider={settings.vlm_provider}
            modelValue={settings.vlm_model}
            models={VLM_MODELS}
            onChange={v => { markDirty('vlm_model'); update('vlm_model', v) }}
          />
        </SettingItem>
      </SettingGroup>
    </SettingSection>
  )
}
