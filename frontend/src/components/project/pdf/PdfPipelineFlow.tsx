import { useTranslation } from 'react-i18next'
import type { FC } from 'react'
import { FileTextIcon, EyeIcon, CheckIcon, XIcon, FlaskIcon, BookIcon } from '../../icons'
import type { IngestStageStatus, IngestTask } from '@/api/http/ingest_queue'

type PipelineVariant = 'compact' | 'full'

interface PdfPipelineFlowProps {
  variant: PipelineVariant
  task: IngestTask | null
}

function useStageLabels() {
  const { t } = useTranslation()
  return [
    { key: 'extract', label: t('pdfPipeline.stage.extract'), Icon: FileTextIcon },
    { key: 'detection', label: t('pdfPipeline.stage.detection'), Icon: EyeIcon },
    { key: 'markdown', label: t('pdfPipeline.stage.markdown'), Icon: FlaskIcon },
    { key: 'patent', label: t('pdfPipeline.stage.patent'), Icon: BookIcon },
  ]
}

type NodeState = 'idle' | 'running' | 'done' | 'failed' | 'skipped'

type StageInfo = { key: string; label: string; Icon: FC<{ size?: number }> }

function getNodeState(task: IngestTask, stage: string): NodeState {
  if (task.status === 'done') return 'done'
  const status: IngestStageStatus | undefined = task.stage_statuses[stage]
  if (status === 'success') return 'done'
  if (status === 'running') return 'running'
  if (status === 'error') return 'failed'
  if (task.status === 'cancelled') return 'skipped'
  return 'idle'
}

function getNodeStates(task: IngestTask, stages: StageInfo[]): NodeState[] {
  return stages.map((stage) => getNodeState(task, stage.key))
}

function NodeIcon({ state }: { state: NodeState }) {
  if (state === 'done') return <CheckIcon size={10} />
  if (state === 'failed') return <XIcon size={10} />
  return null
}

export default function PdfPipelineFlow({
  variant,
  task,
}: PdfPipelineFlowProps) {
  const stages = useStageLabels()
  if (!task) return null

  const states = getNodeStates(task, stages)
  const runningIndex = states.findIndex((s) => s === 'running' || s === 'failed')
  const incompleteIndex = states.findIndex((s) => s === 'idle')
  const activeIndex =
    runningIndex >= 0
      ? runningIndex
      : incompleteIndex >= 0
        ? incompleteIndex
        : stages.length - 1
  const currentStage = stages[activeIndex] ?? stages[0]

  if (variant === 'compact') {
    return (
      <span className="pdf-pipeline-flow pdf-pipeline-flow--compact">
        {stages.map((stage, idx) => {
          const state = states[idx]
          return (
            <span
              key={stage.key}
              className={`pdf-pipeline-node pdf-pipeline-node--${state}`}
              title={`${stage.label}: ${state}`}
            >
              <NodeIcon state={state} />
            </span>
          )
        })}
        <span className="pdf-pipeline-current-label">{currentStage.label}</span>
      </span>
    )
  }

  return (
    <div className="pdf-pipeline-flow pdf-pipeline-flow--full">
      <div className="pdf-pipeline-steps">
        {stages.map((stage, idx) => {
          const state = states[idx]
          const isActive = idx === activeIndex
          return (
            <div key={stage.key} className={`pdf-pipeline-step pdf-pipeline-step--${state}`}>
              <div className="pdf-pipeline-step-icon-wrap">
                <stage.Icon size={16} />
                <span className={`pdf-pipeline-node pdf-pipeline-node--${state}`}>
                  <NodeIcon state={state} />
                </span>
              </div>
              <span className={`pdf-pipeline-step-label${isActive ? ' is-active' : ''}`}>
                {stage.label}
              </span>
              {idx < stages.length - 1 && <span className="pdf-pipeline-connector" />}
            </div>
          )
        })}
      </div>

      <div className="pdf-pipeline-full-meta">
        <span className="pdf-pipeline-full-stage">{currentStage.label}</span>
      </div>
    </div>
  )
}
