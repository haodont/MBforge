import { useTranslation } from 'react-i18next'
import { Badge, Button, InlineAlert, Panel } from '@/components/ui'
import { useDocumentPatentFacts } from '@/api/query/hooks'
import type { DocumentInfo } from '@/api/http/library'
import type { IngestTask } from '@/api/http/ingest_queue'
import type { ResearchArtifactReference, ResearchTaskReference } from '@/api/http/research'
import { ResearchTaskCard } from './ResearchShelf'
import PatentResultStatus from '@/components/project/pdf/PatentResultStatus'

export function ResearchTaskPanel({ reference, documents, tasks, pending, failed, libraryRoot, onOpen }: {
  reference: ResearchTaskReference; documents: DocumentInfo[]; tasks: IngestTask[] | undefined
  pending: boolean; failed: boolean; libraryRoot: string; onOpen: (doc: DocumentInfo) => void
}) {
  const { t } = useTranslation()
  const task = tasks?.find(item => item.id === reference.task_id && item.run_id === reference.run_id && item.doc_id === reference.doc_id)
  const doc = documents.find(item => item.doc_id === reference.doc_id)
  const stage = task?.stage ?? reference.stage
  const title = `${doc?.title || doc?.file_name || reference.doc_id} · ${stage ? t('pdfPipeline.stage.' + stage) : reference.run_id.slice(0, 8)}`
  return <Panel title={title} actions={task ? <Badge tone={task.status === 'failed' ? 'danger' : task.status === 'done' ? 'success' : 'neutral'}>{t('research.task.' + task.status)}</Badge> : undefined}
    collapsible defaultCollapsed className="research-task-context">
    {task ? <ResearchTaskCard task={task} document={doc} libraryRoot={libraryRoot} onOpen={onOpen} />
      : <p className="research-muted">{t(pending ? 'research.loading' : failed ? 'research.tasksError' : 'research.task.referenceUnavailable')}</p>}
  </Panel>
}

export function ResearchArtifactCard({ reference, documents, libraryRoot, onOpen }: {
  reference: ResearchArtifactReference; documents: DocumentInfo[]; libraryRoot: string; onOpen: (doc: DocumentInfo) => void
}) {
  const { t } = useTranslation()
  const query = useDocumentPatentFacts(reference.doc_id, libraryRoot)
  const doc = documents.find(item => item.doc_id === reference.doc_id)
  const loaded = query.data?.ok ? query.data.data : null
  const current = loaded?.run_id === reference.run_id && (loaded.revision ?? 0) >= reference.revision ? loaded : null
  return <Panel title={doc?.title || doc?.file_name || reference.doc_id} className="research-artifact-card"
    actions={<Badge tone="neutral">{current ? t('research.artifactRevision', { reference: reference.revision, current: current.revision }) : `R${reference.revision}`}</Badge>}>
    {query.isPending ? <p>{t('research.loading')}</p> : query.isError ? <InlineAlert tone="danger">{t('research.task.artifactError')}</InlineAlert>
      : current ? <div className="research-artifact-card__summary">
        <span>{t('research.artifactMethods', { count: current.assay_methods.length })}</span>
        <span>{t('research.artifactMeasurements', { count: current.measurements.length })}</span>
        <span>{t('research.artifactReview', { count: current.review_candidates?.length ?? 0 })}</span>
        <PatentResultStatus facts={current} />
      </div> : <p className="research-muted">{t('research.artifactReplaced')}</p>}
    {doc && <Button size="sm" onClick={() => onOpen(doc)}>{t(current ? 'research.openArtifact' : 'research.openCurrentArtifact')}</Button>}
  </Panel>
}
