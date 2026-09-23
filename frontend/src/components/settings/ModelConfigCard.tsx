import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { getLlmEnvConfig, testLlmConnection, type LlmEnvStatus } from '../../api/http/settings'
import Button from '@/components/ui/Button'
import Badge, { type BadgeTone } from '@/components/ui/Badge'
import InlineAlert from '@/components/ui/InlineAlert'
import LlmConfigSection from './model/LlmConfigSection'
import VlmConfigSection from './model/VlmConfigSection'
import LayoutConfigSection from './model/LayoutConfigSection'
import { getUserFacingError } from '@/utils/errors'
import type { SettingsState } from './types'

type ModelType = 'llm' | 'vlm' | 'ocr'

interface Props {
  modelType: ModelType
  title: string
  description?: string
  settings: SettingsState
  setSettings: React.Dispatch<React.SetStateAction<SettingsState>>
  showTest?: boolean
}

const STATUS_TONE: Record<NonNullable<LlmEnvStatus['status']>, BadgeTone> = {
  not_configured: 'neutral',
  ok: 'success',
  unreachable: 'danger',
  http_error: 'danger',
  auth_error: 'danger',
}

export default function ModelConfigCard({
  modelType,
  title,
  description,
  settings,
  setSettings,
  showTest,
}: Props) {
  const { t } = useTranslation()
  const [testStatus, setTestStatus] = useState<LlmEnvStatus | null>(null)
  const [testing, setTesting] = useState(false)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)
  const [dirtyFields, setDirtyFields] = useState<Record<string, boolean>>({})
  const successTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const dirtyTimersRef = useRef<Record<string, ReturnType<typeof setTimeout> | undefined>>({})

  const markDirty = (field: string) => {
    setDirtyFields(d => ({ ...d, [field]: true }))
    const existing = dirtyTimersRef.current[field]
    if (existing) clearTimeout(existing)
    dirtyTimersRef.current[field] = setTimeout(() => {
      setDirtyFields(d => ({ ...d, [field]: false }))
    }, 1000)
  }

  // Load the current active LLM config once on mount (env or saved config).
  // This only reads the resolved config; it does not perform a network probe.
  useEffect(() => {
    if (!showTest) return
    let cancelled = false
    getLlmEnvConfig()
      .then(s => { if (!cancelled) setTestStatus(s) })
      .catch(() => { /* ignore initial load errors; user can hit Test */ })
    return () => { cancelled = true }
  }, [showTest])

  useEffect(() => {
    const dirtyTimers = dirtyTimersRef.current
    return () => {
      if (successTimerRef.current) {
        clearTimeout(successTimerRef.current)
      }
      Object.values(dirtyTimers).forEach(clearTimeout)
    }
  }, [])

  const runTest = async () => {
    setTesting(true)
    if (successTimerRef.current) {
      clearTimeout(successTimerRef.current)
      successTimerRef.current = null
    }
    try {
      const s = await testLlmConnection()
      setTestStatus(s)
      if (s.status === 'ok') {
        setSuccessMessage(t('settings.connectionSucceeded'))
        successTimerRef.current = setTimeout(() => {
          setSuccessMessage(null)
          successTimerRef.current = null
        }, 3000)
      }
    } catch (e) {
      setTestStatus({
        provider: '',
        base_url: '',
        api_key_set: false,
        model: '',
        status: 'unreachable',
        error: getUserFacingError(e),
        http_status: null,
        latency_ms: null,
      })
    } finally {
      setTesting(false)
    }
  }

  const sectionProps = {
    settings,
    setSettings,
    markDirty,
    dirtyFields,
  }

  return (
    <div className="ui-card" style={{ padding: 'var(--space-4)' }}>
      <div className="settings-card-header">
        <div>
          <h3 className="settings-card-title">{title}</h3>
          {description && <p className="settings-card-desc">{description}</p>}
        </div>
        {showTest && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', flexShrink: 0 }}>
            {testStatus && (
              <Badge tone={testing ? 'loading' : STATUS_TONE[testStatus.status]}>
                {testing ? t('settings.testing') : t(`settings.llmStatus.${testStatus.status}`)}
                {!testing && testStatus.latency_ms != null && ` (${testStatus.latency_ms} ms)`}
              </Badge>
            )}
            <Button size="sm" variant="secondary" onClick={runTest} disabled={testing} loading={testing}>
              {t('settings.testConnection')}
            </Button>
          </div>
        )}
      </div>

      {modelType === 'llm' && <LlmConfigSection {...sectionProps} />}
      {modelType === 'vlm' && <VlmConfigSection {...sectionProps} />}
      {modelType === 'ocr' && <LayoutConfigSection {...sectionProps} />}

      {testStatus?.error && (
        <InlineAlert tone="danger" title={t('settings.connectionFailed')} style={{ marginTop: 'var(--space-4)' }}>
          {testStatus.error}
        </InlineAlert>
      )}
      {successMessage && (
        <InlineAlert tone="success" title={successMessage} style={{ marginTop: 'var(--space-4)' }} />
      )}
    </div>
  )
}
