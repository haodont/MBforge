/** Readiness diagnostics tab — subsystem health cards, LLM probe, demo run.
 * Used by Settings > Diagnostics tab. */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  readinessProbeLlm,
  readinessDemoRun,
  type ProbeLlmResult,
  type ReadinessModel,
  type ReadinessSummary,
} from '@/api/http/readiness'
import { ingestList } from '@/api/http/ingest_queue'
import { getUserFacingError } from '@/utils/errors'
import { useReadinessSummary } from '@/api/query/hooks/useReadiness'
import Button from '@/components/ui/Button'
import Caption from '@/components/ui/Caption'

type LampTone = 'ok' | 'warn' | 'error' | 'idle'

const LAMP_COLOR: Record<LampTone, string> = {
  ok: 'var(--success)',
  warn: 'var(--warning)',
  error: 'var(--danger)',
  idle: 'var(--text-secondary, var(--border))',
}

const LAMP_LABEL_KEY: Record<Exclude<LampTone, 'idle'>, string> = {
  ok: 'settings.readiness.state.ready',
  warn: 'settings.readiness.state.attention',
  error: 'settings.readiness.state.error',
}

/** Format a size given in MB as "640 MB" / "1.5 GB". */
function formatSize(mb: number): string {
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`
  return `${mb} MB`
}

function modelTone(status: string): LampTone {
  if (status === 'ready' || status === 'ok') return 'ok'
  if (status === 'error' || status === 'missing') return 'error'
  return 'warn'
}

interface DemoState {
  running: boolean
  tone: 'ok' | 'error' | 'idle'
  message: string | null
}

interface Props {
  libraryRoot: string
}

export default function ReadinessTab({ libraryRoot }: Props) {
  const { t } = useTranslation()
  const {
    data: summary,
    isFetching: loading,
    error: summaryError,
    refetch: refresh,
  } = useReadinessSummary()
  const loadError = summaryError ? getUserFacingError(summaryError) : null
  const [probing, setProbing] = useState(false)
  const [probe, setProbe] = useState<ProbeLlmResult | null>(null)
  const [demo, setDemo] = useState<DemoState>({ running: false, tone: 'idle', message: null })

  const pollTimer = useRef<number | null>(null)
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      if (pollTimer.current !== null) window.clearTimeout(pollTimer.current)
    }
  }, [])

  const handleProbe = async () => {
    setProbing(true)
    try {
      if (mounted.current) setProbe(await readinessProbeLlm())
    } catch (e) {
      if (import.meta.env.DEV) console.warn('[ReadinessTab] probe-llm failed:', e)
      if (mounted.current) {
        setProbe({ ok: false, latency_ms: null, error: getUserFacingError(e), provider: '', model: '' })
      }
    } finally {
      if (mounted.current) setProbing(false)
    }
  }

  const pollDemoTask = useCallback(
    (runId: string) => {
      const tick = async () => {
        try {
          const tasks = await ingestList(libraryRoot)
          if (!mounted.current) return
          const task = tasks.find((x) => x.run_id === runId)
          if (task) {
            if (task.status === 'done') {
              setDemo({ running: false, tone: 'ok', message: t('settings.readiness.demoDone') })
              return
            }
            if (task.status === 'failed' || task.status === 'cancelled') {
              setDemo({
                running: false,
                tone: 'error',
                message: t('settings.readiness.demoTaskFailed', { error: task.error ?? task.status }),
              })
              return
            }
            setDemo({
              running: true,
              tone: 'idle',
              message: t('settings.readiness.demoProgress', {
                stage: task.stage,
              }),
            })
          }
        } catch (e) {
          if (import.meta.env.DEV) console.warn('[ReadinessTab] demo poll failed:', e)
        }
        if (mounted.current) pollTimer.current = window.setTimeout(() => void tick(), 1500)
      }
      void tick()
    },
    [libraryRoot, t],
  )

  const handleDemoRun = async () => {
    setDemo({ running: true, tone: 'idle', message: t('settings.readiness.demoStarting') })
    try {
      const res = await readinessDemoRun()
      if (!mounted.current) return
      if (!res.ok) {
        setDemo({
          running: false,
          tone: 'error',
          message: t('settings.readiness.demoFailed', { error: res.error ?? 'unknown' }),
        })
        return
      }
      if (res.run_id) {
        pollDemoTask(res.run_id)
      } else {
        setDemo({ running: false, tone: 'ok', message: t('settings.readiness.demoDone') })
      }
    } catch (e) {
      if (import.meta.env.DEV) console.warn('[ReadinessTab] demo-run failed:', e)
      if (mounted.current) {
        setDemo({
          running: false,
          tone: 'error',
          message: t('settings.readiness.demoFailed', { error: getUserFacingError(e) }),
        })
      }
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-5)' }}>
      <Caption>{t('settings.readiness.description')}</Caption>

      {loadError && (
        <Caption style={{ color: 'var(--danger)' }}>
          {t('settings.readiness.loadFailed', { error: loadError })}
        </Caption>
      )}
      {!summary && !loadError && <Caption>{t('settings.readiness.checking')}</Caption>}

      {summary && (
        <>
          <LibraryCard summary={summary} />
          <DatabaseCard summary={summary} />
          {summary.models.map((m) => (
            <ModelCardView key={m.id} model={m} />
          ))}
          <OcrCard summary={summary} />
          <LlmCard summary={summary} />
        </>
      )}

      <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
        <Button variant="secondary" size="sm" onClick={() => void refresh()} loading={loading}>
          {t('settings.readiness.refresh')}
        </Button>
        <Button variant="secondary" size="sm" onClick={() => void handleProbe()} loading={probing}>
          {t('settings.readiness.probeLlm')}
        </Button>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => void handleDemoRun()}
          loading={demo.running}
        >
          {t('settings.readiness.demoRun')}
        </Button>
      </div>

      {probe && (
        <Caption style={{ color: probe.ok ? 'var(--success)' : 'var(--danger)' }}>
          {probe.ok
            ? t('settings.readiness.probeOk', { latency: probe.latency_ms ?? '—' })
            : t('settings.readiness.probeFailed', { error: probe.error ?? 'unknown' })}
        </Caption>
      )}
      {demo.message && (
        <Caption
          style={{
            color:
              demo.tone === 'ok'
                ? 'var(--success)'
                : demo.tone === 'error'
                  ? 'var(--danger)'
                  : 'var(--text-primary)',
          }}
        >
          {demo.message}
        </Caption>
      )}
    </div>
  )
}

function Card({
  title,
  tone,
  children,
}: {
  title: string
  tone: LampTone
  children: React.ReactNode
}) {
  const { t } = useTranslation()
  return (
    <div className="ui-card settings-status-card" style={{ padding: 'var(--space-4)' }}>
      <div className="settings-status-card__header">
        <span aria-hidden className="settings-status-dot" style={{ background: LAMP_COLOR[tone] }} />
        <h3 className="settings-status-card__title">{title}</h3>
        {tone !== 'idle' && (
          <Caption style={{ color: LAMP_COLOR[tone], marginLeft: 'auto' }}>
            {t(LAMP_LABEL_KEY[tone])}
          </Caption>
        )}
      </div>
      <div className="settings-status-card__rows">{children}</div>
    </div>
  )
}

function Row({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="settings-status-row">
      <span className="settings-status-row__label">{label}</span>
      <span
        className={
          mono
            ? 'settings-status-row__value settings-status-row__value--mono'
            : 'settings-status-row__value'
        }
      >
        {value}
      </span>
    </div>
  )
}

function LibraryCard({ summary }: { summary: ReadinessSummary }) {
  const { t } = useTranslation()
  const lib = summary.library
  const tone: LampTone = lib.error
    ? 'error'
    : !lib.configured
      ? 'warn'
      : !lib.exists
        ? 'error'
        : lib.writable
          ? 'ok'
          : 'warn'
  const yesNo = (v: boolean) => t(v ? 'settings.readiness.yes' : 'settings.readiness.no')
  return (
    <Card title={t('settings.readiness.library')} tone={tone}>
      <Row label={t('settings.readiness.configured')} value={yesNo(lib.configured)} />
      {lib.path && <Row label={t('settings.readiness.path')} value={lib.path} mono />}
      {lib.configured && (
        <>
          <Row label={t('settings.readiness.exists')} value={yesNo(lib.exists)} />
          <Row label={t('settings.readiness.writable')} value={yesNo(lib.writable)} />
        </>
      )}
      {lib.error && <Row label={t('settings.readiness.error')} value={lib.error} mono />}
      {!lib.configured && (
        <Caption style={{ color: 'var(--warning)' }}>{t('settings.readiness.libraryHint')}</Caption>
      )}
    </Card>
  )
}

function DatabaseCard({ summary }: { summary: ReadinessSummary }) {
  const { t } = useTranslation()
  const db = summary.database
  return (
    <Card title={t('settings.readiness.database')} tone={db.ok ? 'ok' : 'error'}>
      {db.error && <Row label={t('settings.readiness.error')} value={db.error} mono />}
    </Card>
  )
}

function ModelCardView({ model }: { model: ReadinessModel }) {
  const { t } = useTranslation()
  const tone = modelTone(model.status)
  return (
    <Card title={model.name} tone={tone}>
      <Row label={t('settings.readiness.status')} value={model.status} />
      {model.local_path && (
        <Row label={t('settings.readiness.localPath')} value={model.local_path} mono />
      )}
      {model.status !== 'ready' && (
        <>
          {model.expected_size_mb !== null && (
            <Row
              label={t('settings.readiness.expectedSize')}
              value={formatSize(model.expected_size_mb)}
            />
          )}
          {model.cache_dir && (
            <Row label={t('settings.readiness.cacheDir')} value={model.cache_dir} mono />
          )}
          {model.last_error && (
            <Row label={t('settings.readiness.lastError')} value={model.last_error} mono />
          )}
        </>
      )}
    </Card>
  )
}

function OcrCard({ summary }: { summary: ReadinessSummary }) {
  const { t } = useTranslation()
  const ocr = summary.ocr
  const tone: LampTone = ocr.error ? 'error' : ocr.chain.length > 0 ? 'ok' : 'warn'
  return (
    <Card title={t('settings.readiness.ocr')} tone={tone}>
      <Row label={t('settings.readiness.chain')} value={ocr.chain.join(' → ') || '—'} mono />
      {ocr.error && <Row label={t('settings.readiness.error')} value={ocr.error} mono />}
    </Card>
  )
}

function LlmCard({ summary }: { summary: ReadinessSummary }) {
  const { t } = useTranslation()
  const llm = summary.llm
  return (
    <Card title={t('settings.readiness.llm')} tone={llm.configured ? 'ok' : 'warn'}>
      <Row
        label={t('settings.readiness.configured')}
        value={t(llm.configured ? 'settings.readiness.yes' : 'settings.readiness.no')}
      />
      {llm.provider && <Row label={t('settings.readiness.provider')} value={llm.provider} />}
      {llm.model && <Row label={t('settings.readiness.model')} value={llm.model} mono />}
      {llm.base_url && <Row label={t('settings.readiness.baseUrl')} value={llm.base_url} mono />}
      {llm.configured && (
        <Row
          label={t('settings.readiness.apiKey')}
          value={t(
            llm.has_api_key ? 'settings.readiness.apiKeySet' : 'settings.readiness.apiKeyMissing',
          )}
        />
      )}
    </Card>
  )
}
