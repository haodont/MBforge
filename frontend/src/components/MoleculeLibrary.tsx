import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import PageContainer from '@/components/ui/PageContainer'
import Button from '@/components/ui/Button'
import IconButton from '@/components/ui/IconButton'
import Select from '@/components/ui/Select'
import ConfirmDialog from '@/components/ui/ConfirmDialog'
import { AddMoleculeDialog } from '@/components/ui/AddMoleculeDialog'
import { useAppContext } from '@/context/AppContext'
import { useMoleculeLibrary } from '@/hooks/useMoleculeLibrary'
import { useMoleculeAnalysis } from '@/hooks/useMoleculeAnalysis'
import MoleculeFiltersComponent from '@/components/molecule/MoleculeFilters'
import MoleculeSearchBox from '@/components/molecule/MoleculeSearchBox'
import MoleculeTable from '@/components/molecule/MoleculeTable'
import MoleculeCardGrid from '@/components/molecule/MoleculeCardGrid'
import MoleculeAnalysisPanel from '@/components/molecule/MoleculeAnalysisPanel'
import MoleculeDetailDrawer from '@/components/molecule/MoleculeDetailDrawer'
import { GridIcon, SparklesIcon, TableIcon } from '@/components/icons'
import { molAdminBulkDelete, molAdminBulkUpdateStatus } from '@/api/http/molecule_admin'
import { showToast } from '@/hooks/useToast'
import type { MoleculeRecord } from '@/types'
import type { MoleculeSortField } from '@/hooks/useMoleculeLibrary'
import { getUserFacingError } from '@/utils/errors'
import './molecule/MoleculeLibrary.css'

export default function MoleculeLibrary() {
  const { libraryRoot } = useAppContext()
  const { t } = useTranslation()
  const analyzeSelectionLabel = t('mol.analyzeSelection') === 'mol.analyzeSelection'
    ? 'Analyze selection'
    : t('mol.analyzeSelection')

  const {
    molecules,
    totalCount,
    loading,
    error,
    info,
    query,
    filters,
    sort,
    pagination,
    viewMode,
    selectedIds,
    setQuery,
    setFilters,
    setSort,
    setPagination,
    setViewMode,
    toggleSelection,
    selectRange,
    selectCurrentPage: selectCurrentPageAction,
    selectAllResults: selectAllResultsAction,
    clearSelection,
    refresh,
    sourceTypeOptions,
    sourceDocOptions,
  } = useMoleculeLibrary(libraryRoot)

  const selectCurrentPage = selectCurrentPageAction
  const selectAllResults = selectAllResultsAction

  const {
    activeTab,
    setActiveTab,
    analysisInput,
    sarSession,
  } = useMoleculeAnalysis(molecules, selectedIds)

  const [selectedMolecule, setSelectedMolecule] = useState<MoleculeRecord | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [lastClickedId, setLastClickedId] = useState<string | null>(null)
  const [showAddDialog, setShowAddDialog] = useState(false)
  const [isAnalysisOpen, setIsAnalysisOpen] = useState(false)
  const [bulkStatus, setBulkStatus] = useState('')
  const [isBulkUpdating, setIsBulkUpdating] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)
  const [pendingDeleteOpen, setPendingDeleteOpen] = useState(false)
  const [pendingStatus, setPendingStatus] = useState<string | null>(null)

  const totalPages = useMemo(
    () => Math.max(1, Math.ceil(totalCount / pagination.pageSize)),
    [totalCount, pagination.pageSize],
  )

  const handleSort = (field: MoleculeSortField) => {
    setSort({
      field,
      direction: sort.field === field && sort.direction === 'asc' ? 'desc' : 'asc',
    })
  }

  const handleRowClick = (mol: MoleculeRecord) => {
    setSelectedMolecule(mol)
    setDrawerOpen(true)
  }

  const handleDrawerClose = () => {
    setDrawerOpen(false)
    setSelectedMolecule(null)
  }

  const handleSaved = () => {
    refresh()
  }

  const handleBulkStatusChange = async (status: string) => {
    if (!libraryRoot || !status || selectedIds.size === 0) return
    setPendingStatus(null)
    setBulkStatus('')
    setIsBulkUpdating(true)
    const ids = Array.from(selectedIds)
    try {
      const result = await molAdminBulkUpdateStatus(libraryRoot, ids, status)
      if (result.skipped > 0) {
        showToast(t('mol.bulkStatusPartial', { updated: result.updated, failed: result.skipped }), 'warning')
      } else {
        showToast(t('mol.bulkStatusUpdated', { count: result.updated }), 'success')
      }
      clearSelection()
      refresh()
    } catch (error) {
      showToast(t('mol.bulkStatusFailed', { error: getUserFacingError(error, t('common.unknownError')) }), 'error')
    } finally {
      setIsBulkUpdating(false)
    }
  }

  const runDeleteSelected = async () => {
    if (!libraryRoot || selectedIds.size === 0 || isDeleting) return
    setPendingDeleteOpen(false)
    setIsDeleting(true)
    try {
      const deleted = await molAdminBulkDelete(libraryRoot, Array.from(selectedIds))
      clearSelection()
      refresh()
      showToast(t('mol.deleteSuccess', { count: deleted }), 'success')
    } catch (error) {
      showToast(t('mol.deleteFailed', { error: getUserFacingError(error, t('common.unknownError')) }), 'error')
    } finally {
      setIsDeleting(false)
    }
  }

  return (
    <PageContainer>
      <section className="molecule-library-page">
        <div className={`molecule-library-workbench${isAnalysisOpen ? ' has-analysis' : ''}`}>
          <main className="molecule-library-results">
            <section className="molecule-library-filters">
              <div className="molecule-library-filters__toolbar">
                <div className="molecule-library-page__view-toggle" role="group" aria-label={t('mol.viewMode')}>
                  <IconButton
                    ariaLabel={t('mol.viewTable')}
                    title={t('mol.viewTable')}
                    active={viewMode === 'table'}
                    disabled={loading}
                    className="molecule-library-page__view-button molecule-library-page__view-button--table"
                    onClick={() => setViewMode('table')}
                  >
                    <TableIcon size={17} />
                  </IconButton>
                  <IconButton
                    ariaLabel={t('mol.viewCard')}
                    title={t('mol.viewCard')}
                    active={viewMode === 'card'}
                    disabled={loading}
                    className="molecule-library-page__view-button molecule-library-page__view-button--card"
                    onClick={() => setViewMode('card')}
                  >
                    <GridIcon size={17} />
                  </IconButton>
                </div>
                <MoleculeSearchBox
                  query={query}
                  onQueryChange={setQuery}
                  disabled={loading}
                />
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => setShowAddDialog(true)}
                  disabled={!libraryRoot}
                >
                  {t('mol.add')}
                </Button>
              </div>
              <MoleculeFiltersComponent
                filters={filters}
                onFiltersChange={setFilters}
                sourceTypeOptions={sourceTypeOptions}
                sourceDocOptions={sourceDocOptions}
                disabled={loading}
              />
            </section>

            <section className="molecule-library-results__body">
              <div className="molecule-library-bulk-toolbar" role="toolbar" aria-label={t('mol.bulkToolbar')}>
                <div className="molecule-library-bulk-toolbar__summary">
                  <span>{totalCount.toLocaleString()}</span>
                  <span className="molecule-library-results__summary-label">{t('mol.resultsCount', { count: totalCount })}</span>
                </div>
                <strong className="molecule-library-bulk-toolbar__count">
                  {t('mol.selectedCount', { count: selectedIds.size })}
                </strong>
                <Button variant="ghost" size="sm" onClick={selectCurrentPage} disabled={loading || molecules.length === 0 || !selectCurrentPage}>
                  {t('mol.selectCurrentPage')}
                </Button>
                <Button variant="ghost" size="sm" onClick={selectAllResults} disabled={loading || totalCount === 0}>
                  {t('mol.selectAllResults')}
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  icon={<SparklesIcon size={15} />}
                  onClick={() => setIsAnalysisOpen((open) => !open)}
                  disabled={selectedIds.size === 0}
                >
                  {isAnalysisOpen ? t('mol.hideAnalysis') : analyzeSelectionLabel}
                </Button>
                <Select
                  value={bulkStatus}
                  onChange={(next) => {
                    setBulkStatus(next)
                    if (!next) return
                    // Confirm before mutating via the dialog; a stray
                    // Enter/click on the dropdown must not fire the API call.
                    setPendingStatus(next)
                  }}
                  disabled={isBulkUpdating || selectedIds.size === 0}
                  ariaLabel={t('mol.bulkStatus')}
                  placeholder={isBulkUpdating ? t('mol.updatingStatus') : t('mol.bulkStatus')}
                  className="molecule-library-bulk-toolbar__status"
                  options={[
                    { value: 'confirmed', label: t('mol.status.confirmed') },
                    { value: 'pending', label: t('mol.status.pending') },
                    { value: 'corrected', label: t('mol.status.corrected') },
                    { value: 'rejected', label: t('mol.status.rejected') },
                  ]}
                />
                <Button variant="ghost" size="sm" onClick={clearSelection} disabled={selectedIds.size === 0 || isBulkUpdating}>
                  {t('mol.clearSelection')}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setPendingDeleteOpen(true)}
                  disabled={selectedIds.size === 0 || isBulkUpdating || isDeleting}
                >
                  {isDeleting ? t('mol.deleting') : t('mol.deleteSelected')}
                </Button>
              </div>

              <div className="molecule-library-results__scroll-area">
                {info && (
                  <div className="molecule-library-notice" role="status">
                    {t(info, { limit: 10000 })}
                  </div>
                )}
                {error ? (
                  <div className="molecule-library-error" role="alert">{error}</div>
                ) : viewMode === 'table' ? (
                  <MoleculeTable
                    molecules={molecules}
                    loading={loading}
                    selectedIds={selectedIds}
                    sort={sort}
                    onSort={handleSort}
                    onToggleSelect={toggleSelection}
                    onSelectRange={selectRange}
                    onRowClick={handleRowClick}
                    lastClickedId={lastClickedId}
                    setLastClickedId={setLastClickedId}
                  />
                ) : (
                  <MoleculeCardGrid
                    molecules={molecules}
                    loading={loading}
                    selectedIds={selectedIds}
                    onToggleSelect={toggleSelection}
                    onCardClick={handleRowClick}
                  />
                )}
              </div>
            </section>

            <footer className="molecule-library-results__footer">
              <div className="molecule-library-pagination">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setPagination((page) => ({ ...page, page: page.page - 1 }))}
                  disabled={loading || pagination.page <= 1}
                >
                  {t('mol.previous')}
                </Button>
                <span className="molecule-library-pagination__summary">
                  {t('mol.pageInfo', { current: pagination.page, total: totalPages })}
                </span>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setPagination((page) => ({ ...page, page: page.page + 1 }))}
                  disabled={loading || pagination.page >= totalPages}
                >
                  {t('mol.next')}
                </Button>
                <label className="molecule-library-page-size" htmlFor="page-size">
                  <span>{t('mol.pageSize')}</span>
                  <Select
                    id="page-size"
                    value={String(pagination.pageSize)}
                    onChange={(next) =>
                      setPagination({ ...pagination, pageSize: Number(next) })
                    }
                    disabled={loading}
                    showPlaceholder={false}
                    options={[
                      { value: '50', label: '50' },
                      { value: '100', label: '100' },
                      { value: '200', label: '200' },
                    ]}
                  />
                </label>
              </div>

            </footer>
          </main>

          {isAnalysisOpen && (
            <aside className="molecule-library-analysis" aria-label={t('mol.analysisTitle')}>
              <div className="molecule-library-analysis__header">
                <div>
                  <span className="molecule-library-analysis__eyebrow">{t('mol.analysisEyebrow')}</span>
                  <h2>{t('mol.analysisTitle')}</h2>
                </div>
                <Button variant="ghost" size="sm" onClick={() => setIsAnalysisOpen(false)}>
                  {t('common.close')}
                </Button>
              </div>
              <div className="molecule-library-analysis__content">
                <MoleculeAnalysisPanel
                  analysisInput={analysisInput}
                  sarSession={sarSession}
                  activeTab={activeTab}
                  onTabChange={(tab) => setActiveTab(tab)}
                  libraryRoot={libraryRoot}
                  onRefresh={refresh}
                />
              </div>
            </aside>
          )}
        </div>
      </section>

      {libraryRoot && (
        <AddMoleculeDialog
          open={showAddDialog}
          onClose={() => setShowAddDialog(false)}
          libraryRoot={libraryRoot}
          onAdded={handleSaved}
        />
      )}

      <MoleculeDetailDrawer
        molecule={selectedMolecule}
        open={drawerOpen}
        libraryRoot={libraryRoot}
        onClose={handleDrawerClose}
        onSaved={handleSaved}
      />

      <ConfirmDialog
        open={pendingDeleteOpen}
        title={t('mol.deleteSelected')}
        message={t('mol.deleteConfirm', { count: selectedIds.size })}
        confirmLabel={t('mol.deleteSelected')}
        loading={isDeleting}
        onConfirm={() => void runDeleteSelected()}
        onCancel={() => setPendingDeleteOpen(false)}
      />
      <ConfirmDialog
        open={pendingStatus !== null}
        title={t('mol.bulkStatus')}
        message={pendingStatus ? t('mol.bulkStatusConfirm', { count: selectedIds.size, status: pendingStatus }) : ''}
        confirmLabel={t('mol.bulkStatus')}
        loading={isBulkUpdating}
        onConfirm={() => { if (pendingStatus) void handleBulkStatusChange(pendingStatus) }}
        onCancel={() => { setPendingStatus(null); setBulkStatus('') }}
      />
    </PageContainer>
  )
}
