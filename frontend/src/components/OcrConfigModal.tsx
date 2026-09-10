/**
 * OCR backend configuration modal.
 *
 * Shown when a scanned PDF is detected but no cloud OCR backend is
 * configured. User fills API keys for PaddleOCR (optional), saves
 * via the existing settings store, and the backend picks them up on
 * next document load.
 *
 * Each row links to the provider's API-key acquisition page so the
 * user can get a key without leaving the workflow to search docs.
 *
 * Persistence: keys saved to AppConfig.ocr.paddleocr_api_key
 * via `saveSettings`.
 */

import { useState, useCallback, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import Modal from '@/components/ui/Modal'
import Button from '@/components/ui/Button'
import ApiKeyInput from './settings/ApiKeyInput'
import { saveSettings } from '@/api/http/settings'
import { openExternalUrl } from '@/api/http/_utils'
import { getUserFacingError } from '@/utils/errors'
import {
  testOcrPaddleocr,
  getOcrChainStatus,
  type OcrTestResult,
} from '@/api/http/text'

type Backend = 'paddleocr-online' | 'paddleocr-local'



interface FormState {
  paddleocr_api_key: string
  paddleocr_host: string
  paddleocr_model: string
}

const EMPTY: FormState = {
  paddleocr_api_key: '',
  paddleocr_host: '',
  paddleocr_model: '',
}

const ACQUISITION_URLS: Record<Backend, string> = {
  'paddleocr-online': 'https://aistudio.baidu.com/paddleocr',
  'paddleocr-local': '',
}
const DISMISS_KEY_PREFIX = 'mbforge.ocr.dismissForever.'



function openExternal(url: string) {
  if (!url) return
  openExternalUrl(url)
}

export default function OcrConfigModal() {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [missingBackend] = useState<Backend | null>(null)

  const [form, setForm] = useState<FormState>(EMPTY)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [testing, setTesting] = useState<null | 'paddleocr'>(null)
  const [testResults, setTestResults] = useState<{
    paddleocr: OcrTestResult | null
  }>({ paddleocr: null })
  const [chainBackends, setChainBackends] = useState<string[]>([])

  useEffect(() => {
    if (!open) return
    let cancelled = false
    getOcrChainStatus()
      .then(s => {
        if (!cancelled) setChainBackends(s.backends)
      })
      .catch(() => {
        if (!cancelled) setChainBackends([])
      })
    return () => {
      cancelled = true
    }
  }, [open])

  const dismissForever = useCallback(() => {
    if (missingBackend) {
      try {
        localStorage.setItem(`${DISMISS_KEY_PREFIX}${missingBackend}`, '1')
      } catch {
        // ignore quota errors
      }
    }
    setOpen(false)
  }, [missingBackend])

  const save = useCallback(async () => {
    setSaving(true)
    setError(null)
    try {
      const resp = await saveSettings({
        ocr: {
          provider: 'cloud',
          paddleocr_api_key: form.paddleocr_api_key.trim() || null,
          paddleocr_host: form.paddleocr_host.trim() || null,
          paddleocr_model: form.paddleocr_model.trim() || null,
        },
      })
      if (!resp.success) {
        setError(resp.error ?? 'unknown error')
        return
      }
      setOpen(false)
    } catch (e) {
      setError(getUserFacingError(e, t('ocr.config.saveFailed')))
    } finally {
      setSaving(false)
    }
  }, [form, t])

  const runTest = async (which: 'paddleocr') => {
    setTesting(which)
    try {
      const key = form.paddleocr_api_key.trim()
      const result = await testOcrPaddleocr(form.paddleocr_host.trim() || null, key, form.paddleocr_model.trim() || null)
      setTestResults(prev => ({ ...prev, [which]: result }))
    } catch (e) {
      setTestResults(prev => ({
        ...prev,
        [which]: { ok: false, status: null, message: getUserFacingError(e, t('ocr.config.testFailed')) },
      }))
    } finally {
      setTesting(null)
    }
  }

  return (
    <Modal
      open={open}
      onClose={close}
      title={t('ocr.config.title')}
      width={520}
      maxWidth={520}
      footer={
        <>
          <Button variant="ghost" onClick={dismissForever} disabled={saving}>
            {t('ocr.config.dismissForever')}
          </Button>
          <Button variant="secondary" onClick={close} disabled={saving}>
            {t('common.cancel')}
          </Button>
          <Button variant="primary" onClick={save} loading={saving}>
            {t('common.save')}
          </Button>
        </>
      }
    >
      <p style={{ margin: '0 0 16px', color: 'var(--text-secondary)', fontSize: 13 }}>
        {t('ocr.config.description')}
      </p>

      {chainBackends.length > 0 && (
        <div
          style={{
            margin: '0 0 12px',
            padding: '8px 10px',
            fontSize: 12,
            color: 'var(--text-muted)',
            background: 'var(--bg-base)',
            border: '1px solid var(--border)',
            borderRadius: 6,
          }}
        >
          OCR chain: {chainBackends.join(' → ')}
        </div>
      )}

      {error && (
        <div style={{ color: 'var(--danger)', fontSize: 12, marginBottom: 12 }}>
          {error}
        </div>
      )}

      <BackendRow
        label={t('ocr.config.paddleocr')}
        placeholder="bearer token"
        value={form.paddleocr_api_key}
        onChange={v => setForm(s => ({ ...s, paddleocr_api_key: v }))}
        onGetKey={() => openExternal(ACQUISITION_URLS['paddleocr-online'])}
        getKeyLabel={t('ocr.config.getKey')}
        onTest={() => runTest('paddleocr')}
        testing={testing === 'paddleocr'}
        testResult={testResults.paddleocr}
        extra={[
          {
            label: t('ocr.config.paddleocrHost'),
            value: form.paddleocr_host,
            onChange: v => setForm(s => ({ ...s, paddleocr_host: v })),
            placeholder: 'https://paddleocr.aistudio-app.com',
          },
          {
            label: t('ocr.config.paddleocrModel'),
            value: form.paddleocr_model,
            onChange: v => setForm(s => ({ ...s, paddleocr_model: v })),
            placeholder: 'PaddleOCR-VL-1.6',
          },
        ]}
      />

    </Modal>
  )
}

interface BackendRowProps {
  label: string
  placeholder: string
  value: string
  onChange: (v: string) => void
  onGetKey: () => void
  getKeyLabel: string
  onTest: () => void
  testing: boolean
  testResult: OcrTestResult | null
  extra?: Array<{
    label: string
    value: string
    onChange: (v: string) => void
    placeholder: string
  }>
}

function BackendRow({ label, placeholder, value, onChange, onGetKey, getKeyLabel, onTest, testing, testResult, extra }: BackendRowProps) {
  const { t } = useTranslation()
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: 6,
      }}>
        <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)' }}>
          {label}
        </label>
        <button
          type="button"
          onClick={onGetKey}
          style={{
            background: 'none',
            border: 'none',
            color: 'var(--accent)',
            fontSize: 11,
            cursor: 'pointer',
            padding: 0,
            textDecoration: 'underline',
          }}
        >
          {getKeyLabel}
        </button>
      </div>
      <ApiKeyInput value={value} onChange={onChange} placeholder={placeholder} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6 }}>
        <Button variant="secondary" size="sm" onClick={onTest} loading={testing} disabled={!value.trim() || testing}>
          {t('ocr.config.test', { defaultValue: '测试' })}
        </Button>
        {testResult && (
          <span style={{
            fontSize: 11,
            color: testResult.ok ? 'var(--success)' : 'var(--danger)',
          }}>
            {testResult.ok ? '✓ ' : '✗ '}
            {testResult.message}
          </span>
        )}
      </div>
      {extra && extra.length > 0 && (
        <div style={{ marginTop: 8, display: 'grid', gap: 6 }}>
          {extra.map(e => (
            <div key={e.label} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <label style={{ fontSize: 11, color: 'var(--text-muted)', minWidth: 80 }}>
                {e.label}
              </label>
              <input
                type="text"
                value={e.value}
                onChange={ev => e.onChange(ev.target.value)}
                placeholder={e.placeholder}
                style={{
                  flex: 1,
                  padding: '6px 8px',
                  fontSize: 12,
                  border: '1px solid var(--border)',
                  borderRadius: 4,
                  background: 'var(--bg-base)',
                  color: 'var(--text-primary)',
                  fontFamily: 'var(--font-mono, monospace)',
                }}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
