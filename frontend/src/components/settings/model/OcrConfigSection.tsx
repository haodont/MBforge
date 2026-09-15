// OCR config section — fallback priority + per-backend cloud keys.
// Every cloud backend card exposes the same three rows (API key, endpoint,
// model) so no backend is missing a knob the others have.
//
// `ModelConfigCard` injects the shared `settings` / `setSettings` / `markDirty` /
// `dirtyFields`; this component renders the modelType='ocr' groups.

import { useTranslation } from 'react-i18next'
import { openExternalUrl } from '@/api/http/_utils'
import SettingSection, { SettingGroup, SettingItem } from '@/components/ui/SettingSection'
import Button from '@/components/ui/Button'
import Input from '@/components/ui/Input'
import ApiKeyInput from '../ApiKeyInput'
import type { SettingsState } from '../types'

interface Props {
  settings: SettingsState
  setSettings: React.Dispatch<React.SetStateAction<SettingsState>>
  markDirty: (field: string) => void
  dirtyFields: Record<string, boolean>
}

const OCR_LABELS: Record<string, string> = {
  paddleocr: 'PaddleOCR',
  glmocr: 'GLM-OCR',
}

export default function OcrConfigSection({
  settings,
  setSettings,
  markDirty,
  dirtyFields,
}: Props) {
  const { t } = useTranslation()
  const update = <K extends keyof SettingsState>(key: K, value: SettingsState[K]) => {
    setSettings(s => ({ ...s, [key]: value }))
  }

  return (
    <SettingSection>
      <SettingGroup title={t('settings.ocrChain')}>
        <OcrPriorityEditor
          priority={settings.ocr_priority}
          onChange={priority => { markDirty('ocr_priority'); update('ocr_priority', priority) }}
        />
      </SettingGroup>

      <SettingGroup title={t('ocr.backendSection.title')}>
        <p className="ocr-backend-section-desc">
          {t('ocr.backendSection.desc')}
        </p>
        <div className="ocr-backend-grid">
          <BackendKeyRow
            label={t('ocr.config.paddleocr')}
            placeholder="bearer token"
            value={settings.ocr_paddleocr_api_key}
            onChange={v => { markDirty('ocr_paddleocr_api_key'); update('ocr_paddleocr_api_key', v) }}
            getKeyUrl="https://aistudio.baidu.com/paddleocr"
            getKeyLabel={t('ocr.config.getKey')}
            dirty={dirtyFields.ocr_paddleocr_api_key}
            extra={[
              {
                label: t('ocr.config.paddleocrHost'),
                value: settings.ocr_paddleocr_host,
                onChange: v => { markDirty('ocr_paddleocr_host'); update('ocr_paddleocr_host', v) },
                placeholder: 'https://paddleocr.aistudio-app.com',
                dirty: dirtyFields.ocr_paddleocr_host,
              },
              {
                label: t('ocr.config.paddleocrModel'),
                value: settings.ocr_paddleocr_model,
                onChange: v => { markDirty('ocr_paddleocr_model'); update('ocr_paddleocr_model', v) },
                placeholder: 'PaddleOCR-VL-1.6',
                dirty: dirtyFields.ocr_paddleocr_model,
              },
            ]}
          />
          <BackendKeyRow
            label={t('ocr.config.glmocr')}
            placeholder="bearer token"
            value={settings.ocr_glmocr_api_key}
            onChange={v => { markDirty('ocr_glmocr_api_key'); update('ocr_glmocr_api_key', v) }}
            getKeyUrl="https://bigmodel.cn/usercenter/proj-mgmt/apikeys"
            getKeyLabel={t('ocr.config.getKey')}
            dirty={dirtyFields.ocr_glmocr_api_key}
            extra={[
              {
                label: t('ocr.config.glmocrHost'),
                value: settings.ocr_glmocr_base_url,
                onChange: v => { markDirty('ocr_glmocr_base_url'); update('ocr_glmocr_base_url', v) },
                placeholder: 'https://open.bigmodel.cn/api/paas/v4/layout_parsing',
                dirty: dirtyFields.ocr_glmocr_base_url,
              },
              {
                label: t('ocr.config.glmocrModel'),
                value: settings.ocr_glmocr_model,
                onChange: v => { markDirty('ocr_glmocr_model'); update('ocr_glmocr_model', v) },
                placeholder: 'glm-ocr',
                dirty: dirtyFields.ocr_glmocr_model,
              },
            ]}
          />
        </div>
      </SettingGroup>
    </SettingSection>
  )
}

interface BackendKeyRowProps {
  label: string
  placeholder: string
  value: string
  onChange: (v: string) => void
  getKeyUrl?: string
  getKeyLabel?: string
  dirty?: boolean
  extra?: Array<{
    label: string
    value: string
    onChange: (v: string) => void
    placeholder: string
    dirty?: boolean
  }>
}

function BackendKeyRow({ label, placeholder, value, onChange, getKeyUrl, getKeyLabel, dirty, extra }: BackendKeyRowProps) {
  const { t } = useTranslation()
  return (
    <article className="ocr-backend-card">
      <div className="ocr-backend-card__header">
        <label className="ocr-backend-card__title">
          {label}
        </label>
        {getKeyUrl && getKeyLabel && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => openExternalUrl(getKeyUrl)}
            style={{ padding: 0, alignSelf: 'flex-start' }}
          >
            {getKeyLabel}
          </Button>
        )}
      </div>
      <div className="ocr-backend-card__key">
        <ApiKeyInput value={value} onChange={onChange} placeholder={placeholder} />
        {dirty && <span className="setting-dirty-dot" aria-label={t('settings.modified')} />}
      </div>
      {extra && extra.length > 0 && (
        <div className="ocr-backend-card__extra">
          {extra.map(e => (
            <div key={e.label} className="ocr-backend-card__extra-row">
              <label className="ocr-backend-card__extra-label">{e.label}</label>
              <Input
                type="text"
                value={e.value}
                onChange={ev => e.onChange(ev.target.value)}
                placeholder={e.placeholder}
                className="ocr-backend-card__extra-input"
              />
              {e.dirty && <span className="setting-dirty-dot" aria-label={t('settings.modified')} />}
            </div>
          ))}
        </div>
      )}
    </article>
  )
}

function OcrPriorityEditor({
  priority,
  onChange,
}: {
  priority: string[]
  onChange: (priority: string[]) => void
}) {
  const { t } = useTranslation()
  return (
    <SettingItem title={t('settings.ocrPriority')} description={t('settings.ocrPriorityDesc')} layout="stacked">
      <div className="ocr-priority-editor" role="list" aria-label={t('settings.ocrPriority')}>
        {priority.map((provider, index) => (
          <div key={provider} className="ocr-priority-row" role="listitem">
            <span className="ocr-priority-rank">{index + 1}</span>
            <span style={{ flex: 1 }}>{OCR_LABELS[provider] ?? provider}</span>
            <Button
              size="sm"
              variant="ghost"
              aria-label={t('settings.ocrPriorityMoveUp')}
              disabled={index === 0}
              onClick={() => {
                const next = [...priority]
                ;[next[index - 1], next[index]] = [next[index], next[index - 1]]
                onChange(next)
              }}
            >↑</Button>
            <Button
              size="sm"
              variant="ghost"
              aria-label={t('settings.ocrPriorityMoveDown')}
              disabled={index === priority.length - 1}
              onClick={() => {
                const next = [...priority]
                ;[next[index], next[index + 1]] = [next[index + 1], next[index]]
                onChange(next)
              }}
            >↓</Button>
          </div>
        ))}
      </div>
    </SettingItem>
  )
}