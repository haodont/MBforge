import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Tabs, TabPanel, EmptyState } from '../ui'
import AnalyticsTab from '@/components/molecule/analysis/AnalyticsTab'
import RelationsTab from '@/components/molecule/analysis/RelationsTab'
import type { MoleculeRecord } from '@/types'
import type { AnalysisTab } from '@/hooks/useMoleculeAnalysis'

export interface MoleculeAnalysisPanelProps {
  analysisInput: MoleculeRecord[]
  activeTab: AnalysisTab
  onTabChange: (tab: AnalysisTab) => void
  libraryRoot: string | null
  onRefresh: () => void
}

const ANALYSIS_INPUT_LIMIT = 200

export default function MoleculeAnalysisPanel({
  analysisInput,
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

  if (analysisInput.length === 0) {
    return <EmptyState message={t('mol.selectOrImport')} />
  }

  const items = [
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

      <TabPanel activeKey={activeTab} tabKey="analytics">
        <AnalyticsTab molecules={effectiveInput} libraryRoot={libraryRoot} onRefresh={onRefresh} />
      </TabPanel>

      <TabPanel activeKey={activeTab} tabKey="relations">
        <RelationsTab molecules={effectiveInput} />
      </TabPanel>
    </div>
  )
}
