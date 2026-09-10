// General section — language and theme.

import { useTranslation } from 'react-i18next'
import SettingSection, { SettingGroup } from '@/components/ui/SettingSection'
import { SelectField } from './SettingRow'
import type { SettingsState } from './types'

interface Props {
  settings: SettingsState
  setSettings: React.Dispatch<React.SetStateAction<SettingsState>>
}

export default function GeneralSection({ settings, setSettings }: Props) {
  const { t } = useTranslation()
  return (
    <SettingSection>
      <SettingGroup title={t('settings.appearance')}>
        <SelectField
          label={t('settings.theme')}
          description={t('settings.themeDesc')}
          value={settings.theme}
          onChange={v => setSettings(s => ({ ...s, theme: v }))}
          options={[
            { value: 'dark', label: t('settings.dark') },
            { value: 'light', label: t('settings.light') },
            { value: 'system', label: t('settings.system') },
          ]}
        />
        <SelectField
          label={t('settings.language')}
          description={t('settings.languageDesc')}
          value={settings.language}
          onChange={v => setSettings(s => ({ ...s, language: v }))}
          options={[
            { value: 'zh', label: '中文' },
            { value: 'en', label: 'English' },
          ]}
        />
      </SettingGroup>
    </SettingSection>
  )
}
