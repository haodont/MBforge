import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Badge, Button, CollapsibleSection, EmptyState, LoadingState } from '@/components/ui'
import { useDocumentPatentFacts } from '@/api/query/hooks/useDocumentArtifacts'
import { resolveDocumentEvidenceBatch } from '@/api/http/library'
import type {
  PatentFactsCharacterization,
  PatentFactsSynthesisRoute,
} from '@/api/http/library'
import { showToast } from '@/hooks/useToast'
import { getUserFacingError } from '@/utils/errors'

/**
 * What the document itself says about one compound: its printed name, the spectra
 * and elemental data printed for it, and the preparation routes that make it.
 *
 * Every string here is copied verbatim out of the patent by the deterministic
 * extractors — nothing is derived from a structure and nothing is typed by a model.
 * ``attribution: "unresolved"`` means the passage prints no designation the rules
 * could bind; such a passage is still shown (it exists in the document) and is
 * handed to the association pass rather than guessed at.
 */
export default function DocumentFactsSection({
  docId,
  labelKeys,
  libraryRoot,
  onOpenPdf,
}: {
  docId: string | null
  /** The molecule's designation keys, in the artifact's key space. */
  labelKeys: string[]
  libraryRoot?: string | null
  onOpenPdf?: (
    docId: string,
    page: number | null,
    bbox: { x0: number; y0: number; x1: number; y1: number } | null,
    evidenceId?: string | null,
  ) => void
}) {
  const { t } = useTranslation()
  const [opening, setOpening] = useState(false)
  const query = useDocumentPatentFacts(docId, libraryRoot ?? null)
  const facts = query.data?.ok ? query.data.data : null
  const wanted = useMemo(
    () => new Set(labelKeys.map((key) => key.toLowerCase())),
    [labelKeys],
  )

  const names = useMemo(
    () => (facts?.names ?? []).filter((item) => wanted.has(item.label_key.toLowerCase())),
    [facts, wanted],
  )
  const characterizations = useMemo(
    () =>
      (facts?.characterizations ?? []).filter((item) =>
        wanted.has(item.label_key.toLowerCase()),
      ),
    [facts, wanted],
  )
  const routes = useMemo(
    () =>
      (facts?.synthesis_steps ?? []).filter((item) =>
        wanted.has(item.label_key.toLowerCase()),
      ),
    [facts, wanted],
  )

  if (!docId || !libraryRoot || labelKeys.length === 0) return null
  if (query.isLoading) return <LoadingState message={t('molecule.facts.loading')} />
  if (!facts) return null
  if (names.length === 0 && characterizations.length === 0 && routes.length === 0) {
    return null
  }

  const openEvidence = async (evidenceId: string, page: number | null) => {
    if (!docId || !onOpenPdf) return
    setOpening(true)
    try {
      const rows = await resolveDocumentEvidenceBatch(docId, [evidenceId], libraryRoot)
      const row = rows.find((candidate) => candidate.evidence_id === evidenceId)
      onOpenPdf(
        docId,
        row?.page ?? page,
        row ? { x0: row.bbox[0], y0: row.bbox[1], x1: row.bbox[2], y1: row.bbox[3] } : null,
        evidenceId,
      )
    } catch (error) {
      showToast({ message: getUserFacingError(error), type: 'error' })
    } finally {
      setOpening(false)
    }
  }

  const techniqueLabel = (item: PatentFactsCharacterization) =>
    t(`molecule.facts.technique.${item.technique}`)

  return (
    <div className="molecule-detail__document-facts" data-testid="molecule-document-facts">
      <CollapsibleSection title={t('molecule.facts.names')} defaultOpen>
        {names.length === 0 ? (
          <EmptyState message={t('molecule.facts.namesEmpty')} />
        ) : (
          <ul className="molecule-detail__facts-list">
            {names.map((item) => (
              <li key={item.name_id}>
                <span className="molecule-detail__fact-label">{item.label_raw}</span>
                <code className="molecule-detail__fact-text">{item.name_raw}</code>
                {item.attribution === 'unresolved' ? (
                  <Badge tone="warning">{t('molecule.facts.unattributed')}</Badge>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </CollapsibleSection>

      <CollapsibleSection
        title={t('molecule.facts.characterization')}
        badge={characterizations.length || undefined}
        defaultOpen
      >
        {characterizations.length === 0 ? (
          <EmptyState message={t('molecule.facts.characterizationEmpty')} />
        ) : (
          <ul className="molecule-detail__facts-list">
            {characterizations.map((item) => (
              <li key={item.characterization_id}>
                <Badge tone="info">{techniqueLabel(item)}</Badge>
                <code className="molecule-detail__fact-text">{item.raw_text}</code>
                {item.attribution === 'unresolved' ? (
                  <Badge tone="warning">{t('molecule.facts.unattributed')}</Badge>
                ) : null}
                {onOpenPdf && item.evidence_ids[0] ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={opening}
                    onClick={() => void openEvidence(item.evidence_ids[0], item.page)}
                  >
                    {t('molecule.facts.openPdf')}
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </CollapsibleSection>

      <CollapsibleSection
        title={t('molecule.facts.synthesis')}
        badge={routes.length || undefined}
        defaultOpen
      >
        {routes.length === 0 ? (
          <EmptyState message={t('molecule.facts.synthesisEmpty')} />
        ) : (
          routes.map((route: PatentFactsSynthesisRoute) => (
            <article className="molecule-detail__route" key={route.route_id}>
              <header>
                <strong>{route.title || route.product_label || route.label_raw}</strong>
                {route.yield_raw ? <Badge tone="neutral">{route.yield_raw}</Badge> : null}
                {route.attribution === 'unresolved' ? (
                  <Badge tone="warning">{t('molecule.facts.unattributed')}</Badge>
                ) : null}
              </header>
              {route.method_note ? (
                <p className="molecule-detail__route-note">{route.method_note}</p>
              ) : null}
              {route.steps.length > 0 ? (
                <ol className="molecule-detail__route-steps">
                  {route.steps.map((step) => (
                    <li key={`${route.route_id}-${step.step_no}`}>{step.text}</li>
                  ))}
                </ol>
              ) : null}
              {onOpenPdf && route.evidence_ids[0] ? (
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={opening}
                  onClick={() => void openEvidence(route.evidence_ids[0], route.page_start)}
                >
                  {t('molecule.facts.openPdf')}
                </Button>
              ) : null}
            </article>
          ))
        )}
      </CollapsibleSection>
    </div>
  )
}
