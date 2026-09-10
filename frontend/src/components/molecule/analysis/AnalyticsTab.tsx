import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Tabs, TabPanel } from '../../ui'
import SubstructureSearchPanel from '../analytics/SubstructureSearchPanel'
import AnalogSearchPanel from '../analytics/AnalogSearchPanel'
import ClusterPanel from '../analytics/ClusterPanel'
import RelationPanel from '../analytics/RelationPanel'
import DedupPanel from '../analytics/DedupPanel'
import type { MoleculeRecord } from '@/types'

type AnalyticsInnerTab = 'substructure' | 'analogs' | 'clusters' | 'relations' | 'dedup'

export interface AnalyticsTabProps {
  molecules: MoleculeRecord[]
  libraryRoot: string | null
  onRefresh: () => void
}

export default function AnalyticsTab({ molecules, libraryRoot: _libraryRoot, onRefresh }: AnalyticsTabProps) {
  const { t } = useTranslation()
  const [activeTab, setActiveTab] = useState<AnalyticsInnerTab>('substructure')

  const items = [
    { key: 'substructure', label: t('analytics.tabs.substructure') },
    { key: 'analogs', label: t('analytics.tabs.analogs') },
    { key: 'clusters', label: t('analytics.tabs.clusters') },
    { key: 'relations', label: t('analytics.tabs.relations') },
    { key: 'dedup', label: t('analytics.tabs.dedup') },
  ]

  return (
    <div>
      <Tabs items={items} activeKey={activeTab} onChange={(key) => setActiveTab(key as AnalyticsInnerTab)} />
      <TabPanel activeKey={activeTab} tabKey="substructure">
        <SubstructureSearchPanel />
      </TabPanel>
      <TabPanel activeKey={activeTab} tabKey="analogs">
        <AnalogSearchPanel molecules={molecules} />
      </TabPanel>
      <TabPanel activeKey={activeTab} tabKey="clusters">
        <ClusterPanel molecules={molecules} />
      </TabPanel>
      <TabPanel activeKey={activeTab} tabKey="relations">
        <RelationPanel molecules={molecules} />
      </TabPanel>
      <TabPanel activeKey={activeTab} tabKey="dedup">
        <DedupPanel molecules={molecules} onComplete={onRefresh} />
      </TabPanel>
    </div>
  )
}
