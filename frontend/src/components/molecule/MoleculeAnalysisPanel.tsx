import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Tabs, TabPanel, EmptyState } from '../ui'
import SessionOverview from '@/components/sar/SessionOverview'
import OverviewTab from '@/components/sar/OverviewTab'
import RGroupTab from '@/components/sar/RGroupTab'
import CliffsTab from '@/components/sar/CliffsTab'
import AnalyticsTab from '@/components/molecule/analysis/AnalyticsTab'
import RelationsTab from '@/components/molecule/analysis/RelationsTab'
import { moleculesToSession } from '@/components/sar/utils'
import type { MoleculeRecord, SARSession } from '@/types'
import type { AnalysisTab } from '@/hooks/useMoleculeAnalysis'

export interface MoleculeAnalysisPanelProps {
  analysisInput: MoleculeRecord[]
  sarSession: SARSession | null
  activeTab: AnalysisTab
  onTabChange: (tab: AnalysisTab) => void
  libraryRoot: string | null
  onRefresh: () => void
}

const ANALYSIS_INPUT_LIMIT = 200

export default function MoleculeAnalysisPanel({
  analysisInput,
  sarSession: _sarSession,
  activeTab,
  onTabChange,
  libraryRoot,
  onRefresh,
}: MoleculeAnalysisPanelProps) {
  const { t } = useTranslation()

  const effectiveInput = useMemo(
    () => analysisInput.slice(0, ANALYSIS_INPUT_LIMIT),
    [analysisInput],
  )

  const effectiveSession = useMemo(
    () => (effectiveInput.length > 0 ? moleculesToSession(effectiveInput) : null),
    [effectiveInput],
  )

  if (analysisInput.length === 0) {
    return <EmptyState message={t('mol.selectOrImport')} />
  }

  const items = [
    { key: 'overview', label: t('analysis.tab.overview') },
    { key: 'rgroup', label: t('analysis.tab.rgroup') },
    { key: 'cliffs', label: t('analysis.tab.cliffs') },
    { key: 'analytics', label: t('analysis.tab.analytics') },
    { key: 'relations', label: t('analysis.tab.relations') },
  ]

  return (
    <div>
      {analysisInput.length > ANALYSIS_INPUT_LIMIT && (
        <div
          style={{
            marginBottom: 12,
            padding: '10px 14px',
            borderRadius: 8,
            background: 'var(--info-muted)',
            color: 'var(--info)',
            fontSize: 13,
          }}
          role="status"
        >
          {t('mol.analysisLimited')}
        </div>
      )}

      <Tabs
        items={items}
        activeKey={activeTab}
        onChange={(key) => onTabChange(key as AnalysisTab)}
      />

      <TabPanel activeKey={activeTab} tabKey="overview">
        {effectiveSession && (
          <>
            <SessionOverview session={effectiveSession} />
            <OverviewTab session={effectiveSession} selectedCompoundId={null} onSelect={() => {}} />
          </>
        )}
      </TabPanel>

      <TabPanel activeKey={activeTab} tabKey="rgroup">
        {effectiveSession && <RGroupTab session={effectiveSession} onSelectCompound={() => {}} />}
      </TabPanel>

      <TabPanel activeKey={activeTab} tabKey="cliffs">
        {effectiveSession && libraryRoot && (
          <CliffsTab session={effectiveSession} libraryRoot={libraryRoot} />
        )}
      </TabPanel>

      <TabPanel activeKey={activeTab} tabKey="analytics">
        <AnalyticsTab molecules={effectiveInput} libraryRoot={libraryRoot} onRefresh={onRefresh} />
      </TabPanel>

      <TabPanel activeKey={activeTab} tabKey="relations">
        <RelationsTab molecules={effectiveInput} />
      </TabPanel>
    </div>
  )
}
