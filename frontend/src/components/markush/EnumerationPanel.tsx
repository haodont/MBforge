/**
 * Markush enumeration panel.
 *
 * Mounted when viewing a confirmed scaffold. Allows users to:
 * - Select sites and their fragments for enumeration
 * - Preview theoretical count
 * - Run bounded enumeration
 * - View generated candidates
 * - Confirm candidates into molecules table
 */

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  useMarkushEnumerationPreview,
  useMarkushEnumerationResults,
  useMarkushEnumerationRun,
  useMarkushGeneratedDecide,
  useMarkushSites,
} from '@/api/query/useMarkush'
import type { SiteSelection } from '@/api/http/markush'
import Button from '../ui/Button'
import CollapsibleSection from '../ui/CollapsibleSection'
import InlineAlert from '../ui/InlineAlert'
import Input from '../ui/Input'
import { LoadingState } from '../ui/LoadingState'
import Tag from '../ui/Tag'

interface EnumerationPanelProps {
  libraryRoot: string
  scaffoldId: string
}

export default function EnumerationPanel({
  libraryRoot,
  scaffoldId,
}: EnumerationPanelProps) {
  const { t } = useTranslation()
  const sites = useMarkushSites(libraryRoot, scaffoldId)

  const [selections, setSelections] = useState<SiteSelection[]>([])
  const [requestedLimit, setRequestedLimit] = useState('1000')
  const [activeRunId, setActiveRunId] = useState<string | null>(null)

  const preview = useMarkushEnumerationPreview(libraryRoot)
  const run = useMarkushEnumerationRun(libraryRoot)
  const results = useMarkushEnumerationResults(libraryRoot, activeRunId)
  const decide = useMarkushGeneratedDecide(libraryRoot)

  const handleToggleFragment = (
    siteLabel: string,
    atomMapNum: number,
    fragmentId: string,
  ) => {
    setSelections((prev) => {
      const existing = prev.find((s) => s.site_label === siteLabel)
      if (!existing) {
        return [
          ...prev,
          {
            site_label: siteLabel,
            atom_map_num: atomMapNum,
            fragments: [fragmentId],
          },
        ]
      }
      const hasFragment = existing.fragments.includes(fragmentId)
      if (hasFragment) {
        const updated = {
          ...existing,
          fragments: existing.fragments.filter((f) => f !== fragmentId),
        }
        return updated.fragments.length > 0
          ? prev.map((s) => (s.site_label === siteLabel ? updated : s))
          : prev.filter((s) => s.site_label !== siteLabel)
      } else {
        return prev.map((s) =>
          s.site_label === siteLabel
            ? { ...s, fragments: [...s.fragments, fragmentId] }
            : s,
        )
      }
    })
  }

  const handlePreview = () => {
    if (selections.length === 0) return
    preview.mutate({
      scaffold_id: scaffoldId,
      selection: selections,
    })
  }

  const handleRun = () => {
    if (selections.length === 0) return
    run.mutate(
      {
        scaffold_id: scaffoldId,
        selection: selections,
        requested_limit: Number(requestedLimit),
      },
      {
        onSuccess: (data) => {
          setActiveRunId(data.run_id)
        },
      },
    )
  }

  const handleConfirmGenerated = (generatedId: string) => {
    if (!activeRunId) return
    decide.mutate({
      generated_id: generatedId,
      action: 'confirm',
      reason: 'User confirmed enumeration product',
    })
  }

  if (sites.isLoading) return <LoadingState variant="spinner" message={t('common.loading', 'Loading...')} />
  if (sites.isError)
    return <InlineAlert tone="danger">{t('common.error', 'Error loading sites')}</InlineAlert>

  const sitesList = sites.data || []

  return (
    <section
      data-testid="markush-enumeration-panel"
      style={{
        padding: '12px 14px',
        borderTop: '1px solid var(--border)',
        display: 'flex',
        flexDirection: 'column',
        gap: 16,
      }}
    >
      <div style={{ fontSize: 14, fontWeight: 600 }}>
        {t('markush.enumeration.title', 'Markush 结构枚举')}
      </div>

      {/* Site selection */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {sitesList.map((site) => {
          const selection = selections.find(
            (s) => s.site_label === site.site_label,
          )
          const siteOptions = (site.options || []) as Array<{
            option_id: string
            fragment_id?: string
            definition_text?: string
            normalized_smiles?: string
          }>

          return (
            <CollapsibleSection
              key={site.site_id}
              defaultOpen
              title={`${site.site_label} [*:${site.atom_map_num}] — ${
                selection?.fragments.length || 0
              } / ${siteOptions.length} selected`}
            >
              <div
                style={{
                  paddingLeft: 16,
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 4,
                  marginTop: 6,
                }}
              >
                {siteOptions.length === 0 && (
                  <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                    {t(
                      'markush.enumeration.noOptions',
                      'No options defined. Add R-group definitions first.',
                    )}
                  </div>
                )}
                {siteOptions.map((opt) => {
                  const isSelected = selection?.fragments.includes(
                    opt.fragment_id || '',
                  )
                  return (
                    <label
                      key={opt.option_id}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 6,
                        fontSize: 12,
                        cursor: 'pointer',
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() =>
                          handleToggleFragment(
                            site.site_label,
                            site.atom_map_num ?? 0,
                            opt.fragment_id || '',
                          )
                        }
                        disabled={!opt.fragment_id}
                      />
                      <span>
                        {opt.definition_text || opt.normalized_smiles || '—'}
                      </span>
                    </label>
                  )
                })}
              </div>
            </CollapsibleSection>
          )
        })}
      </div>

      {/* Controls */}
      <div
        style={{
          display: 'flex',
          gap: 8,
          alignItems: 'flex-end',
          flexWrap: 'wrap',
        }}
      >
        <Button
          size="sm"
          variant="secondary"
          onClick={handlePreview}
          disabled={selections.length === 0 || preview.isPending}
          loading={preview.isPending}
        >
          {preview.isPending
            ? t('common.loading', 'Loading...')
            : t('markush.enumeration.preview', '预览组合数')}
        </Button>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <label
            htmlFor="requested-limit"
            style={{ fontSize: 11, color: 'var(--text-secondary)' }}
          >
            {t('markush.enumeration.limit', 'Max products')}
          </label>
          <Input
            id="requested-limit"
            type="number"
            value={requestedLimit}
            onChange={(e) => setRequestedLimit(e.target.value)}
            style={{ width: 100 }}
            min="1"
            max="100000"
          />
        </div>

        <Button
          size="sm"
          variant="primary"
          onClick={handleRun}
          disabled={selections.length === 0 || run.isPending}
          loading={run.isPending}
        >
          {run.isPending
            ? t('common.running', 'Running...')
            : t('markush.enumeration.run', '执行枚举')}
        </Button>
      </div>

      {/* Preview result */}
      {preview.isSuccess && (
        <InlineAlert tone="info">
          <div style={{ fontWeight: 600, marginBottom: 6 }}>
            {t('markush.enumeration.previewResult', 'Preview result')}:
          </div>
          <div>
            {t('markush.enumeration.theoreticalCount', 'Theoretical count')}:{' '}
            <strong>{preview.data.theoretical_count}</strong>
          </div>
          {preview.data.truncated && (
            <div style={{ marginTop: 6 }}>
              {t('markush.enumeration.truncated', 'Truncated above limit')}
            </div>
          )}
        </InlineAlert>
      )}

      {/* Run result */}
      {run.isSuccess && (
        <InlineAlert tone="success">
          {t('markush.enumeration.runSuccess', 'Enumeration completed')}:{' '}
          <strong>{run.data.written_count}</strong>{' '}
          {t('markush.enumeration.productsGenerated', 'products generated')}.
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setActiveRunId(run.data.run_id)}
            style={{ marginLeft: 8 }}
          >
            {t('markush.enumeration.viewResults', '查看结果')}
          </Button>
        </InlineAlert>
      )}

      {/* Generated candidates */}
      {activeRunId && results.isSuccess && (
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 8,
            maxHeight: 400,
            overflowY: 'auto',
            padding: 8,
            border: '1px solid var(--border)',
            borderRadius: 4,
          }}
        >
          <div style={{ fontSize: 13, fontWeight: 600, position: 'sticky', top: 0, backgroundColor: 'var(--bg)' }}>
            {t('markush.enumeration.results', 'Generated candidates')} (
            {results.data.length})
          </div>
          {results.data.map((candidate) => (
            <div
              key={candidate.generated_id}
              style={{
                padding: 8,
                backgroundColor: 'var(--bg-base)',
                borderRadius: 4,
                fontSize: 12,
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
              }}
            >
              <div style={{ flex: 1 }}>
                <div style={{ fontFamily: 'monospace', marginBottom: 4 }}>
                  {candidate.canonical_smiles}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
                  {t('markush.enumeration.validationStatus', 'Validation')}:{' '}
                  {candidate.validation_status} |{' '}
                  {t('markush.enumeration.reviewStatus', 'Review')}:{' '}
                  {candidate.review_status}
                </div>
              </div>
              {candidate.review_status === 'pending' && (
                <Button
                  size="sm"
                  variant="primary"
                  onClick={() => handleConfirmGenerated(candidate.generated_id)}
                  disabled={decide.isPending}
                >
                  {t('markush.enumeration.confirm', '确认入库')}
                </Button>
              )}
              {candidate.review_status === 'confirmed' && (
                <Tag tone="success">✓ {t('markush.enumeration.confirmed', 'Confirmed')}</Tag>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Errors */}
      {preview.isError && (
        <InlineAlert tone="danger">
          {t('markush.enumeration.previewError', 'Preview failed')}:{' '}
          {String((preview.error as Error).message || preview.error)}
        </InlineAlert>
      )}
      {run.isError && (
        <InlineAlert tone="danger">
          {t('markush.enumeration.runError', 'Enumeration failed')}:{' '}
          {String((run.error as Error).message || run.error)}
        </InlineAlert>
      )}
    </section>
  )
}
