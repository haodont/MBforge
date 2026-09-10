// About section — version info, config directory, danger zone.

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import SettingSection, { SettingGroup } from '@/components/ui/SettingSection'
import { CustomField } from './SettingRow'
import Button from '@/components/ui/Button'
import { showToast } from '../../hooks/useToast'
import { fetchBuildInfo, exportSettings } from '../../api/http/settings'
import { getUserFacingError } from '@/utils/errors'

interface Props {
  onReset: () => void
  onOpenConfig: () => void
}

// __APP_VERSION__ is injected by vite.config.ts from package.json version
// (kept in sync with constants.yaml app.version via scripts/generate_constants.py).

export default function AboutSection({ onReset, onOpenConfig }: Props) {
  const { t } = useTranslation()
  const [confirmingReset, setConfirmingReset] = useState(false)
  const [tierInfo, setTierInfo] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)

  const handleFetchBuildInfo = () => {
    try {
      const info = fetchBuildInfo()
      setTierInfo(`${info.version} (${info.platform})`)
    } catch (e) {
      setTierInfo(getUserFacingError(e, t('settings.buildInfoFailed')))
    }
  }

  const handleExport = async () => {
    setExporting(true)
    try {
      // Simplified: write next to the config dir as .mbforge-config-<timestamp>.json
      const ts = new Date().toISOString().replace(/[:.]/g, '-')
      const target = `mbforge-config-${ts}.json`
      await exportSettings(target)
      showToast(`${t('settings.exported')}: ${target}`, 'success')
    } catch (e) {
      showToast(getUserFacingError(e, t('settings.exportFailed')), 'error')
    } finally {
      setExporting(false)
    }
  }

  const handleHardReset = () => {
    onReset()
    setConfirmingReset(false)
    showToast(t('settings.resetHint'), 'info')
  }

  return (
    <SettingSection>
      <SettingGroup title={t('settings.version')}>
        <CustomField label="MBForge">
          <span style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono, monospace)' }}>
            v{__APP_VERSION__}
          </span>
        </CustomField>
        <CustomField label={t('settings.buildInfo')}>
          <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
            <Button size="sm" variant="ghost" onClick={handleFetchBuildInfo}>
              {t('settings.fetchBuildInfo')}
            </Button>
            {tierInfo && (
              <span style={{ fontSize: 'var(--text-sm)', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono, monospace)' }}>
                {tierInfo}
              </span>
            )}
          </div>
        </CustomField>
      </SettingGroup>

      <SettingGroup title={t('settings.configFile')}>
        <CustomField label={t('settings.configFile')}>
          <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
            <Button size="sm" variant="secondary" onClick={onOpenConfig}>
              {t('settings.openConfigDir')}
            </Button>
            <Button
              size="sm"
              variant="secondary"
              loading={exporting}
              onClick={handleExport}
            >
              {t('settings.exportConfig')}
            </Button>
          </div>
        </CustomField>
      </SettingGroup>

      <SettingGroup title={t('settings.dangerZone')}>
        <CustomField label={t('settings.resetToDefault')}>
          {confirmingReset ? (
            <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
              <Button size="sm" variant="danger" onClick={handleHardReset}>
                {t('settings.confirmReset')}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirmingReset(false)}>
                {t('common.cancel')}
              </Button>
            </div>
          ) : (
            <Button
              size="sm"
              variant="danger"
              onClick={() => setConfirmingReset(true)}
            >
              {t('settings.reset')}
            </Button>
          )}
        </CustomField>
      </SettingGroup>
    </SettingSection>
  )
}