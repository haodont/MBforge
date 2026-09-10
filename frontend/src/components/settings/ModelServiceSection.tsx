// Model service section — Python sidecar (FastAPI) config + health check.

import { useState, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { sidecarStatus } from '../../api/http/sidecar'
import SettingSection, { SettingGroup } from '@/components/ui/SettingSection'
import {
  TextField,
  NumberField,
  ToggleField,
  CustomField,
} from './SettingRow'
import Button from '@/components/ui/Button'
import { showToast } from '../../hooks/useToast'
import type { SettingsState } from './types'
import { getUserFacingError } from '@/utils/errors'

interface Props {
  settings: SettingsState
  setSettings: React.Dispatch<React.SetStateAction<SettingsState>>
}

interface SidecarStatus {
  healthy: boolean
  state: string
  restartCount: number
  uptimeSecs: number
  lastError: string | null
}

export default function ModelServiceSection({ settings, setSettings }: Props) {
  const { t } = useTranslation()
  const [status, setStatus] = useState<SidecarStatus | null>(null)
  const [testing, setTesting] = useState(false)

  const testConnection = useCallback(async () => {
    setTesting(true)
    try {
      const res = await sidecarStatus()
      setStatus(res)
      if (res.healthy) {
        showToast(t('settings.serverOk', { secs: res.uptimeSecs }), 'success')
      } else {
        showToast(
          t('settings.serverDown', { err: res.lastError || t('settings.serverUnknown') }),
          'error',
        )
      }
    } catch (e) {
      showToast(t('settings.serverTestFailed', { err: getUserFacingError(e) }), 'error')
    } finally {
      setTesting(false)
    }
  }, [t])

  return (
    <SettingSection>
      <SettingGroup title={t('settings.serverNetwork')}>
        <TextField
          label={t('settings.serverHost')}
          description={t('settings.serverHostDesc')}
          value={settings.server_host}
          onChange={v => setSettings(s => ({ ...s, server_host: v }))}
          placeholder="127.0.0.1"
          monospace
        />
        <NumberField
          label={t('settings.serverPort')}
          description={t('settings.serverPortDesc')}
          value={settings.server_port}
          onChange={v => setSettings(s => ({ ...s, server_port: v }))}
          min={1}
          max={65535}
          step={1}
          width={120}
        />
        <CustomField label={t('settings.testConnection')}>
          <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
            <Button
              variant="secondary"
              size="sm"
              loading={testing}
              onClick={testConnection}
            >
              {t('settings.testNow')}
            </Button>
            {status && (
              <span
                style={{
                  fontSize: 'var(--text-sm)',
                  color: status.healthy ? 'var(--success)' : 'var(--danger)',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 'var(--space-1)',
                }}
              >
                <span
                  aria-hidden
                  className="settings-status-dot"
                  style={{ background: status.healthy ? 'var(--success)' : 'var(--danger)' }}
                />
                {status.healthy
                  ? t('settings.serverOnline', { secs: status.uptimeSecs })
                  : t('settings.serverOffline', { err: status.lastError || t('settings.serverUnknown') })}
              </span>
            )}
          </div>
        </CustomField>
      </SettingGroup>

      <SettingGroup title={t('settings.serverLifecycle')}>
        <ToggleField
          label={t('settings.serverAutoStart')}
          description={t('settings.serverAutoStartDesc')}
          value={settings.server_auto_start}
          onChange={v => setSettings(s => ({ ...s, server_auto_start: v }))}
        />
        <NumberField
          label={t('settings.startupTimeout')}
          description={t('settings.startupTimeoutDesc')}
          value={settings.server_startup_timeout}
          onChange={v => setSettings(s => ({ ...s, server_startup_timeout: v }))}
          min={10}
          max={600}
          step={5}
          width={100}
          placeholder="120"
        />
        <NumberField
          label={t('settings.healthInterval')}
          description={t('settings.healthIntervalDesc')}
          value={settings.server_health_check_interval}
          onChange={v => setSettings(s => ({ ...s, server_health_check_interval: v }))}
          min={1}
          max={60}
          step={1}
          width={100}
          placeholder="5"
        />
      </SettingGroup>

      <SettingGroup title={t('settings.modelCache')}>
        <TextField
          label={t('settings.modelCacheDir')}
          description={t('settings.modelCacheDirDesc')}
          value={settings.model_cache_dir}
          onChange={v => setSettings(s => ({ ...s, model_cache_dir: v }))}
          placeholder={t('settings.modelCacheDirPlaceholder')}
          monospace
        />
      </SettingGroup>
    </SettingSection>
  )
}