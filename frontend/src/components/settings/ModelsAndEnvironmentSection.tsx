// Models & Environment tab — model downloads, model service config,
// and readiness diagnostics.

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import Tabs, { TabPanel } from '@/components/ui/Tabs'
import ModelsTab from '@/components/settings/ModelsTab'
import ModelServiceSection from '@/components/settings/ModelServiceSection'
import ReadinessTab from '@/components/settings/ReadinessTab'
import type { SettingsState } from '@/components/settings/types'

type Tab = 'models' | 'model_service' | 'readiness'

interface Props {
  settings: SettingsState
  setSettings: React.Dispatch<React.SetStateAction<SettingsState>>
  libraryRoot: string
}

const TABS: Array<{ key: Tab; labelKey: string }> = [
  { key: 'models', labelKey: 'settings.tabs.models' },
  { key: 'model_service', labelKey: 'settings.tabs.modelService' },
  { key: 'readiness', labelKey: 'settings.tabs.readiness' },
]

export default function ModelsAndEnvironmentSection({ settings, setSettings, libraryRoot }: Props) {
  const { t } = useTranslation()
  const [tab, setTab] = useState<Tab>('models')

  return (
    <div>
      <Tabs
        id="models-and-environment-tabs"
        items={TABS.map(({ key, labelKey }) => ({ key, label: t(labelKey) }))}
        activeKey={tab}
        onChange={key => setTab(key as Tab)}
        variant="segment"
        size="sm"
      />
      <TabPanel activeKey={tab} tabKey="models" tabsId="models-and-environment-tabs">
        <ModelsTab />
      </TabPanel>
      <TabPanel activeKey={tab} tabKey="model_service" tabsId="models-and-environment-tabs">
        <ModelServiceSection settings={settings} setSettings={setSettings} />
      </TabPanel>
      <TabPanel activeKey={tab} tabKey="readiness" tabsId="models-and-environment-tabs">
        <ReadinessTab libraryRoot={libraryRoot} />
      </TabPanel>
    </div>
  )
}
