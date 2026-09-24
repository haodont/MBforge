// Local layout section — the only text/layout producer the pipeline runs.
//
// There is no OCR provider to pick or authenticate: page text and typed
// regions come from the local Hiro-Layout producer, so the knobs here are that
// producer's own parameters. `ModelConfigCard` injects the shared
// `settings` / `setSettings` / `markDirty` / `dirtyFields` and renders this for
// the OCR tab.

import { useTranslation } from 'react-i18next'
import SettingSection, { SettingGroup } from '@/components/ui/SettingSection'
import { NumberField, ToggleField } from '../SettingRow'
import type { SettingsState } from '../types'

interface Props {
  settings: SettingsState
  setSettings: React.Dispatch<React.SetStateAction<SettingsState>>
  markDirty: (field: string) => void
  dirtyFields: Record<string, boolean>
}

export default function LayoutConfigSection({
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
      <SettingGroup title={t('settings.layout')}>
        <NumberField
          label={t('settings.layoutConfThreshold')}
          description={t('settings.layoutConfThresholdDesc')}
          value={settings.layout_conf_threshold}
          onChange={v => {
            markDirty('layout_conf_threshold')
            update('layout_conf_threshold', v)
          }}
          min={0}
          max={1}
          step={0.05}
          width={100}
          dirty={dirtyFields.layout_conf_threshold}
        />
        <ToggleField
          label={t('settings.layoutCrossModel')}
          description={t('settings.layoutCrossModelDesc')}
          value={settings.layout_cross_model}
          onChange={v => {
            markDirty('layout_cross_model')
            update('layout_cross_model', v)
          }}
          dirty={dirtyFields.layout_cross_model}
        />
      </SettingGroup>
    </SettingSection>
  )
}
