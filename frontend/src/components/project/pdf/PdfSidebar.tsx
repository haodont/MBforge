/**
 * Right-hand result pane of the PDF workbench.
 *
 * Hosts the evidence / molecules tabs (and their collapse toggle). The
 * molecules tab lists the current page's detections with their patent facts;
 * the evidence tab delegates to ``PageEvidencePane``.
 */

import type { Dispatch, SetStateAction } from 'react'
import { useTranslation } from 'react-i18next'
import Tabs from '@/components/ui/Tabs'
import Button from '@/components/ui/Button'
import IconButton from '@/components/ui/IconButton'
import { ChevronLeftIcon, ChevronRightIcon } from '@/components/icons'
import { RdkitStructure } from '@/components/chat/markdownExtensions'
import PageEvidencePane from '@/components/project/PageEvidencePane'
import MoleculePatentFacts from './MoleculePatentFacts'
import type { ExtractionResult } from '@/types'
import type { PatentFactsArtifact } from '@/api/http/library'
import type { PdfSidePaneTab } from './usePdfSidebarState'

interface Props {
  docId: string
  libraryRoot: string
  currentPage: number
  isResultPaneCollapsed: boolean
  setIsResultPaneCollapsed: Dispatch<SetStateAction<boolean>>
  sidePaneTab: PdfSidePaneTab
  setSidePaneTab: Dispatch<SetStateAction<PdfSidePaneTab>>
  selectedEvidenceId: string | null
  detections: ExtractionResult[]
  isDetecting: boolean
  canDetect: boolean
  patentFacts: PatentFactsArtifact | null
  onDetect: () => void
  setSelectedDetection: Dispatch<SetStateAction<number | null>>
  setEditingDetectionIndex: Dispatch<SetStateAction<number | null>>
}

export default function PdfSidebar({
  docId,
  libraryRoot,
  currentPage,
  isResultPaneCollapsed,
  setIsResultPaneCollapsed,
  sidePaneTab,
  setSidePaneTab,
  selectedEvidenceId,
  detections,
  isDetecting,
  canDetect,
  patentFacts,
  onDetect,
  setSelectedDetection,
  setEditingDetectionIndex,
}: Props) {
  const { t } = useTranslation()

  return (
    <aside className={`pdf-document-sidebar${isResultPaneCollapsed ? ' is-collapsed' : ''}`} aria-label={t('pdf.moleculesHeader')}>
      {isResultPaneCollapsed ? (
        <IconButton
          size={32}
          className="pdf-document-sidebar__collapse-button"
          onClick={() => setIsResultPaneCollapsed(false)}
          ariaLabel={t('pdf.sidebarExpand')}
          title={t('pdf.sidebarExpandTitle')}
        >
          <ChevronLeftIcon size={16} />
        </IconButton>
      ) : (
        <>
          <div className="pdf-document-sidebar__tabs">
            <Tabs
              items={[
                { key: 'evidence', label: t('pdf.tabEvidence') },
                { key: 'molecules', label: t('pdf.tabMolecules') },
              ]}
              activeKey={sidePaneTab}
              onChange={(key) => setSidePaneTab(key === 'molecules' ? 'molecules' : 'evidence')}
              variant="underline"
              size="sm"
              fullWidth
              style={{ flex: 1, minWidth: 0 }}
            />
            <IconButton
              size={28}
              className="pdf-document-sidebar__collapse-button"
              onClick={() => setIsResultPaneCollapsed(true)}
              ariaLabel={t('pdf.sidebarCollapse')}
              title={t('pdf.sidebarCollapseTitle')}
            >
              <ChevronRightIcon size={16} />
            </IconButton>
          </div>
          <div className="pdf-document-sidebar__content">
            {sidePaneTab === 'evidence' && (
              <PageEvidencePane
                docId={docId}
                page={currentPage}
                libraryRoot={libraryRoot}
                selectedEvidenceId={selectedEvidenceId}
              />
            )}
            {sidePaneTab === 'molecules' && (
              <section className="pdf-current-molecules">
                <div className="pdf-current-molecules__header">
                  <div><strong>{t('pdf.moleculesHeader')}</strong><span>{t('pdf.moleculesCount', { count: detections.length })}</span></div>
                  <Button variant="primary" onClick={onDetect} disabled={isDetecting || !canDetect}>
                    {isDetecting ? t('pdf.detecting') : t('pdf.detect')}
                  </Button>
                </div>
                {detections.length === 0 ? <p className="pdf-current-molecules__empty">{t('pdf.moleculesEmpty')}</p> : detections.map((detection, index) => (
                  <button type="button" className="pdf-current-molecule" key={`${detection.esmiles}-${index}`} onClick={() => { setSelectedDetection(index); setEditingDetectionIndex(index) }}>
                    {detection.esmiles ? <RdkitStructure smiles={detection.smiles || detection.esmiles} /> : <span className="pdf-current-molecule__fallback">{t('pdf.structureUnavailable')}</span>}
                    <span className="pdf-current-molecule__meta"><strong>{detection.name || t('pdf.moleculeFallbackName', { index: index + 1 })}</strong><span>{Math.round(detection.moldet_conf * 100)}%</span></span>
                    <MoleculePatentFacts facts={patentFacts} detection={detection} />
                  </button>
                ))}
              </section>
            )}
          </div>
        </>
      )}
    </aside>
  )
}
