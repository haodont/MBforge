// Settings page top-level tabs: General / PDF Processing /
// Models & Environment / About.

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import Tabs from '@/components/ui/Tabs'
import ScrollColumn from '@/components/ui/ScrollColumn'
import GeneralTab from '@/components/settings/GeneralTab'
import ModelsAndEnvironmentSection from '@/components/settings/ModelsAndEnvironmentSection'
import AboutTab from '@/components/settings/AboutTab'
import PdfProcessingTab from '@/components/settings/PdfProcessingTab'
import type { SettingsState } from '@/components/settings/types'

type TabKey = 'general' | 'pdf_processing' | 'models_environment' | 'about'

interface Props {
  settings: SettingsState
  setSettings: React.Dispatch<React.SetStateAction<SettingsState>>
  libraryRoot: string
  onReset: () => void
  onOpenConfig: () => void
}

const TABS: Array<{ key: TabKey; labelKey: string }> = [
  { key: 'general', labelKey: 'settings.tabs.general' },
  { key: 'pdf_processing', labelKey: 'settings.tabs.pdfProcessing' },
  { key: 'models_environment', labelKey: 'settings.tabs.modelsEnvironment' },
  { key: 'about', labelKey: 'settings.tabs.about' },
]

export default function SettingsTabs({
  settings,
  setSettings,
  libraryRoot,
  onReset,
  onOpenConfig,
}: Props) {
  const { t } = useTranslation()
  const [activeTab, setActiveTab] = useState<TabKey>('general')

  return (
    <div className="settings-tabs">
      <Tabs
        items={TABS.map(({ key, labelKey }) => ({ key, label: t(labelKey) }))}
        activeKey={activeTab}
        onChange={(key) => setActiveTab(key as TabKey)}
        variant="underline"
        size="sm"
      />
      <ScrollColumn>
        <div className="settings-tab-content">
          {activeTab === 'general' && (
            <GeneralTab settings={settings} setSettings={setSettings} />
          )}
          {activeTab === 'pdf_processing' && (
            <PdfProcessingTab settings={settings} setSettings={setSettings} />
          )}
          {activeTab === 'models_environment' && (
            <ModelsAndEnvironmentSection
              settings={settings}
              setSettings={setSettings}
              libraryRoot={libraryRoot}
            />
          )}
          {activeTab === 'about' && (
            <AboutTab onReset={onReset} onOpenConfig={onOpenConfig} />
          )}
        </div>
      </ScrollColumn>
    </div>
  )
}
