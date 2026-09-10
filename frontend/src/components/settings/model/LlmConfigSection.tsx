import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import Caption from '@/components/ui/Caption'
import Button from '@/components/ui/Button'
import SettingSection, { SettingGroup, SettingItem } from '@/components/ui/SettingSection'
import CollapsibleSection from '@/components/ui/CollapsibleSection'
import { fetchLlmModels } from '@/api/http/settings'
import { getUserFacingError } from '@/utils/errors'
import {
  NumberField,
  ProviderField,
  SelectField,
  ToggleField,
} from '../SettingRow'
import { ModelSelector } from '../ModelComponents'
import {
  LLM_MODELS,
  PROVIDER_META,
  type ModelMap,
  type ModelOption,
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

  // Models fetched live from the provider (see fetchLlmModels). They are
  // merged ahead of the preset suggestions so the dropdown reflects the real
  // catalog, while presets remain as a fallback when the probe is unavailable.
  const [fetchedModels, setFetchedModels] = useState<ModelOption[]>([])
  const [fetchState, setFetchState] = useState<'idle' | 'loading' | 'done' | 'error'>('idle')
  const [fetchError, setFetchError] = useState<string | null>(null)

  const modelOptions = useMemo(() => {
    const presets = LLM_MODELS[settings.llm_provider] ?? []
    const seen = new Set<string>()
    const merged: ModelOption[] = []
    for (const m of [...fetchedModels, ...presets]) {
      if (seen.has(m.value)) continue
      seen.add(m.value)
      merged.push(m)
    }
    return merged
  }, [fetchedModels, settings.llm_provider])

  const resetFetchedModels = () => {
    setFetchedModels([])
    setFetchState('idle')
    setFetchError(null)
  }

  const runFetchModels = async () => {
    setFetchState('loading')
    setFetchError(null)
    try {
      const res = await fetchLlmModels({
        provider: settings.llm_provider,
        base_url: settings.llm_base_url,
        api_key: settings.llm_api_key,
      })
      if (!res.success) {
        setFetchError(res.error ?? t('settings.fetchModelsFailed'))
        setFetchState('error')
        return
      }
      setFetchedModels((res.models ?? []).map(m => ({ value: m.value, label: m.label })))
      setFetchState('done')
    } catch (e) {
      setFetchError(getUserFacingError(e, t('settings.fetchModelsFailed')))
      setFetchState('error')
    }
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
            // A different provider has a different model catalog — drop stale
            // fetched suggestions instead of mixing lists from two providers.
            resetFetchedModels()
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
          <div className="settings-model-fetch">
            <ModelSelector
              provider={settings.llm_provider}
              modelValue={settings.llm_model}
              models={{ [settings.llm_provider]: modelOptions }}
              onChange={v => { markDirty('llm_model'); update('llm_model', v) }}
            />
            <Button
              size="sm"
              variant="ghost"
              onClick={() => void runFetchModels()}
              loading={fetchState === 'loading'}
              disabled={fetchState === 'loading'}
              title={t('settings.fetchModelsDesc')}
              ariaLabel={t('settings.fetchModelsDesc')}
            >
              {fetchState === 'loading' ? t('settings.fetchModelsLoading') : t('settings.fetchModels')}
            </Button>
          </div>
          {fetchState === 'error' && fetchError && (
            <Caption color="var(--danger)" style={{ marginTop: 'var(--space-1)', display: 'block' }}>
              {t('settings.fetchModelsError', { message: fetchError })}
            </Caption>
          )}
          {fetchState === 'done' && fetchedModels.length === 0 && (
            <Caption style={{ marginTop: 'var(--space-1)', display: 'block' }}>
              {t('settings.fetchModelsEmpty')}
            </Caption>
          )}
          {fetchState === 'done' && fetchedModels.length > 0 && (
            <Caption style={{ marginTop: 'var(--space-1)', display: 'block' }}>
              {t('settings.fetchModelsSuccess', { total: fetchedModels.length })}
            </Caption>
          )}
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

      <CollapsibleSection title={t('settings.llmMoleculeTool')} defaultOpen={false}>
        <SettingGroup>
          <ToggleField
            label={t('settings.moleculeToolEnabled')}
            description={t('settings.moleculeToolEnabledDesc')}
            value={settings.llm_molecule_tool_enabled}
            onChange={v => { markDirty('llm_molecule_tool_enabled'); update('llm_molecule_tool_enabled', v) }}
            dirty={dirtyFields.llm_molecule_tool_enabled}
          />
          <NumberField
            label={t('settings.moleculeToolMaxChars')}
            description={t('settings.moleculeToolMaxCharsDesc')}
            value={settings.llm_molecule_tool_max_chars}
            onChange={v => { markDirty('llm_molecule_tool_max_chars'); update('llm_molecule_tool_max_chars', v) }}
            min={1000}
            max={100000}
            step={500}
            width={120}
            dirty={dirtyFields.llm_molecule_tool_max_chars}
          />
        </SettingGroup>
      </CollapsibleSection>
    </SettingSection>
  )
}
