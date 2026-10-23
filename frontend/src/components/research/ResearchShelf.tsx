import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useDocuments, useIngestQueue, usePatentAnalysis, useDocumentPatentFacts } from '@/api/query/hooks'
import { useAppContext } from '@/context/AppContext'
import { Badge, Button, InlineAlert, Panel } from '@/components/ui'
import { FileTextIcon, ChevronRightIcon, QueueIcon } from '@/components/icons'
import { deduplicateTasksByDocId } from '@/components/project/queueUtils'
import type { DocumentInfo } from '@/api/http/library'
import type { IngestTask } from '@/api/http/ingest_queue'
import type { PdfSidePaneTab } from '@/types'
import { getUserFacingError } from '@/utils/errors'
import PatentResultStatus from '@/components/project/pdf/PatentResultStatus'

export default function ResearchShelf() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { libraryRoot, openTab, researchDocumentIds, setResearchDocumentIds } = useAppContext()
  const docs = useDocuments()
  const queue = useIngestQueue(libraryRoot)
  const analysis = usePatentAnalysis()
  const submitting = useRef(false)
  const [notice, setNotice] = useState('')
  const [analysisError, setAnalysisError] = useState('')
  const documents = docs.data?.documents ?? []
  const tasks = deduplicateTasksByDocId(queue.data ?? []).sort((a, b) => b.updated_at - a.updated_at)
  const openDocument = (doc: DocumentInfo, initialSidePaneTab?: PdfSidePaneTab) => openTab({
    type: 'pdf', title: doc.title || doc.file_name, libraryRoot, initialSidePaneTab,
    doc: { doc_id: doc.doc_id, path: doc.file_name, doc_type: 'pdf', title: doc.title || doc.file_name },
  })
  const analyze = async () => {
    const ids = documents.filter(doc => researchDocumentIds.includes(doc.doc_id)).map(doc => doc.doc_id)
    if (!ids.length || submitting.current) return
    submitting.current = true
    setNotice('')
    setAnalysisError('')
    try {
      const result = await analysis.mutateAsync(ids)
      if (!result.success) throw new Error(t('research.analysisFailed'))
      setNotice(t('research.analysisQueued', { count: result.enqueued, skipped: result.skipped }))
    } catch (error) {
      setAnalysisError(getUserFacingError(error, t('common.unknownError')))
    } finally { submitting.current = false }
  }

  return (
    <aside className="research-shelf" aria-label={t('research.materials')}>
      <div className="research-shelf__intro">
        <span className="research-eyebrow">{t('research.workspace')}</span>
        <h2>{t('research.materials')}</h2>
        <p>{t('research.materialsHint')}</p>
      </div>
      <Panel title={t('research.documents')} actions={<Button size="sm" variant="ghost" onClick={() => void navigate('/workspace')}>{t('research.manage')}</Button>}
        footer={<Button size="sm" disabled={docs.isError || !researchDocumentIds.length} loading={analysis.isPending} onClick={() => void analyze()}>{t('research.analyzeSelected')}</Button>}>
        {notice && <InlineAlert tone="success">{notice}</InlineAlert>}
        {analysisError && <InlineAlert tone="danger">{analysisError}</InlineAlert>}
        {docs.isPending ? <p className="research-muted">{t('research.loading')}</p>
          : docs.isError ? <InlineAlert tone="danger">{t('research.documentsError')} <Button size="sm" onClick={() => void docs.refetch()}>{t('research.retry')}</Button></InlineAlert>
            : documents.length === 0 ? <div className="research-shelf__empty"><FileTextIcon size={24} /><p>{t('research.noDocuments')}</p><Button onClick={() => void navigate('/workspace')}>{t('research.import')}</Button></div>
              : documents.slice(0, 5).map(doc => (
                <div key={doc.doc_id} className="research-document">
                  <Button variant="ghost" className="research-document__name" icon={<FileTextIcon size={16} />} onClick={() => openDocument(doc)}>{doc.title || doc.file_name}</Button>
                  <div className="research-document__meta">
                    <span>{t('research.pages', { count: doc.page_count })}</span>
                    <Button size="sm" variant={researchDocumentIds.includes(doc.doc_id) ? 'secondary' : 'ghost'}
                      disabled={!researchDocumentIds.includes(doc.doc_id) && researchDocumentIds.length >= 8}
                      ariaPressed={researchDocumentIds.includes(doc.doc_id)}
                      onClick={() => setResearchDocumentIds(ids => ids.includes(doc.doc_id) ? ids.filter(id => id !== doc.doc_id) : [...ids, doc.doc_id])}>
                      {t(researchDocumentIds.includes(doc.doc_id) ? 'research.selected' : 'research.addContext')}
                    </Button>
                  </div>
                </div>
              ))}
      </Panel>
      <Panel title={t('research.tasks')} actions={<Button size="sm" variant="ghost" onClick={() => void navigate('/queue')} icon={<ChevronRightIcon size={14} />}>{t('research.allTasks')}</Button>}>
        {queue.isPending ? <p className="research-muted">{t('research.loading')}</p>
          : queue.isError ? <InlineAlert tone="danger">{t('research.tasksError')} <Button size="sm" onClick={() => void queue.refetch()}>{t('research.retry')}</Button></InlineAlert>
            : tasks.length === 0 ? <div className="research-shelf__empty"><QueueIcon size={22} /><p>{t('research.noTasks')}</p></div>
              : tasks.slice(0, 4).map(task => (
                <ResearchTaskCard
                  key={task.id}
                  task={task}
                  document={documents.find(doc => doc.doc_id === task.doc_id)}
                  libraryRoot={libraryRoot}
                  onOpen={doc => openDocument(doc, 'analysis')}
                />
              ))}
      </Panel>
      <p className="research-shelf__note">{t('research.evidenceNote')}</p>
    </aside>
  )
}

export function ResearchTaskCard({
  task,
  document,
  libraryRoot,
  onOpen,
}: {
  task: IngestTask
  document: DocumentInfo | undefined
  libraryRoot: string
  onOpen: (doc: DocumentInfo) => void
}) {
  const { t } = useTranslation()
  const factsQuery = useDocumentPatentFacts(task.doc_id, libraryRoot)
  const refetchPatentFacts = factsQuery.refetch
  useEffect(() => {
    if (task.status === 'done') void refetchPatentFacts()
  }, [task.run_id, task.status, refetchPatentFacts])
  const loaded = factsQuery.data?.ok ? factsQuery.data.data : null
  const facts = loaded?.run_id === task.run_id ? loaded : null
  const fallbackReason = t('patentAnalysis.error.' + (facts?.llm?.error_code ?? 'unknown'))

  return (
    <div className="research-task">
      <div className="research-task__main">
        {document
          ? <Button variant="ghost" className="research-task__document" ariaLabel={t('research.task.openResult', { name: document.title || document.file_name })} onClick={() => onOpen(document)}>{document.title || document.file_name}</Button>
          : <span className="research-task__document">{task.file_path.split(/[\\/]/).pop()}</span>}
        <Badge tone={task.status === 'failed' ? 'danger' : task.status === 'done' ? 'success' : 'neutral'}>{t('research.task.' + task.status)}</Badge>
      </div>
      {factsQuery.isPending ? <p className="research-task__no-artifact">{t('research.loading')}</p>
        : factsQuery.isError ? <InlineAlert tone="danger">{t('research.task.artifactError')}</InlineAlert>
          : facts ? (
        <div className="research-task__analysis">
          <Badge tone={facts.analysis_status === 'fallback' ? 'warning' : facts.analysis_status === 'succeeded' ? 'success' : 'neutral'}>
            {t('patentAnalysis.status.' + (facts.analysis_status ?? 'disabled'))}
          </Badge>
          <Badge tone="neutral">{t('patentAnalysis.mode.' + (facts.extraction_mode ?? 'deterministic'))}</Badge>
          <span>{t('patentAnalysis.candidates')}: {facts.review_candidates?.length ?? 0}</span>
          <span>{t('patentAnalysis.issues')}: {facts.issues.length}</span>
          <PatentResultStatus facts={facts} />
          {facts.analysis_status === 'fallback' && <InlineAlert tone="warning">{t('patentAnalysis.fallback', { reason: fallbackReason })}</InlineAlert>}
        </div>
          ) : task.status === 'done' ? <p className="research-task__no-artifact">{t('research.task.noCurrentArtifact')}</p> : null}
    </div>
  )
}
