import { useState, useEffect, useCallback, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { useAppContext } from '@/context/AppContext'
import PageContainer from '@/components/ui/PageContainer'
import PageTitle from '@/components/ui/PageTitle'
import AlertBanner from '@/components/ui/AlertBanner'
import Button from '@/components/ui/Button'
import SettingsTabs from '@/components/settings/SettingsTabs'
import { useSettings, useSaveSettings } from '@/api/query/hooks'
import { getConfigDir } from '@/api/http/settings'
import { useTheme } from '@/hooks/useTheme'
import i18n from '@/i18n'
import { showToast } from '@/hooks/useToast'
import { getUserFacingError } from '@/utils/errors'
import {
  DEFAULT_SETTINGS,
  flattenSettings,
  toBackendPayload,
  isSettingsEqual,
  type SettingsState,
} from '@/components/settings/types'

export default function SettingsPage() {
  const { t } = useTranslation()
  const { libraryRoot } = useAppContext()
  const { setTheme } = useTheme()

  const [settings, setSettings] = useState<SettingsState>(DEFAULT_SETTINGS)
  const [initialSettings, setInitialSettings] = useState<SettingsState>(DEFAULT_SETTINGS)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')
  const [saveSuccess, setSaveSuccess] = useState(false)
  const [buttonSaved, setButtonSaved] = useState(false)
  const [saveErrorShake, setSaveErrorShake] = useState(false)

  const settingsQuery = useSettings()
  const saveSettingsMutation = useSaveSettings()

  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([])

  const isDirty = !isSettingsEqual(settings, initialSettings)

  // Seed the form from the backend once (React Query cache handles dedupe
  // across SettingsPage remounts); the form keeps local state for dirty
  // tracking and Cancel.
  useEffect(() => {
    if (!settingsQuery.isSuccess) return
    const data = settingsQuery.data
    if (data.settings) {
      const loaded = flattenSettings(data.settings)
      setSettings(loaded)
      setInitialSettings(loaded)
    } else if (data.error) {
      setError(data.error)
    }
  }, [settingsQuery.isSuccess, settingsQuery.data])

  const handleSave = useCallback(async () => {
    setIsLoading(true)
    setError('')
    setSaveSuccess(false)
    try {
      const payload = toBackendPayload(settings)
      const resp = await saveSettingsMutation.mutateAsync(payload)
      if (resp.success) {
        setSaveSuccess(true)
        setButtonSaved(true)
        setInitialSettings(settings)
        setTheme(settings.theme)
        void i18n.changeLanguage(settings.language)
        timersRef.current.push(setTimeout(() => setSaveSuccess(false), 3000))
        timersRef.current.push(setTimeout(() => setButtonSaved(false), 1500))
      } else {
        const msg = resp.error || t('settings.saveFailed')
        setError(msg)
        setSaveErrorShake(true)
        showToast(msg, 'error')
        timersRef.current.push(setTimeout(() => setSaveErrorShake(false), 300))
      }
    } catch (e) {
      const msg = t('settings.saveFailed') + ': ' + getUserFacingError(e)
      setError(msg)
      setSaveErrorShake(true)
      showToast(msg, 'error')
      timersRef.current.push(setTimeout(() => setSaveErrorShake(false), 300))
    } finally {
      setIsLoading(false)
    }
  }, [settings, t, setTheme, saveSettingsMutation])

  const handleReset = useCallback(() => {
    setSettings(DEFAULT_SETTINGS)
  }, [])

  const handleCancel = useCallback(() => {
    setSettings(initialSettings)
    setError('')
    setSaveSuccess(false)
  }, [initialSettings])

  const handleOpenConfigDir = useCallback(async () => {
    try {
      const path = await getConfigDir()
      showToast(path, 'info')
    } catch (e) {
      showToast(getUserFacingError(e, t('settings.configFile')), 'error')
    }
  }, [t])

  const loading = isLoading || settingsQuery.isLoading

  // Reflect a failed initial settings load the same way the old manual
  // loadSettings did (banner + toast), so the user is not left staring at
  // the default form as if it were the saved state.
  const loadError =
    settingsQuery.isError && !settingsQuery.data
      ? t('settings.loadFailed') + ': ' + getUserFacingError(settingsQuery.error)
      : ''

  useEffect(() => {
    if (!loadError) return
    setError(loadError)
    showToast(loadError, 'error')
  }, [loadError])

  useEffect(() => {
    return () => {
      timersRef.current.forEach(clearTimeout)
      timersRef.current = []
    }
  }, [])

  return (
    <PageContainer>
      <div className="settings-page-header">
        <div className="settings-page-heading">
          <PageTitle>{t('settings.title')}</PageTitle>
          <p className="settings-save-scope">{t('settings.saveScope')}</p>
        </div>
        <div className="settings-page-actions">
          <span
            className={`settings-unsaved-indicator ${isDirty ? 'settings-unsaved-indicator--visible' : 'settings-unsaved-indicator--hidden'}`}
          >
            {isDirty ? '● ' + t('settings.unsavedChangesTitle') : ''}
          </span>
          <Button variant="secondary" onClick={handleCancel} disabled={loading}>
            {t('common.cancel')}
          </Button>
          <Button
            variant={buttonSaved ? 'success' : 'primary'}
            onClick={handleSave}
            disabled={loading || !isDirty}
            loading={loading}
            className={saveErrorShake ? 'settings-save-button--error' : undefined}
          >
            {loading ? t('settings.saving') : buttonSaved ? t('settings.saved') + ' ✓' : t('common.save')}
          </Button>
        </div>
      </div>

      {error && (
        <AlertBanner
          variant="danger"
          message={error}
          onDismiss={() => setError('')}
          className="settings-alert"
        />
      )}
      {saveSuccess && (
        <AlertBanner
          variant="success"
          message={t('settings.saved')}
          className="settings-alert"
        />
      )}

      <SettingsTabs
        settings={settings}
        setSettings={setSettings}
        libraryRoot={libraryRoot}
        onReset={handleReset}
        onOpenConfig={handleOpenConfigDir}
      />
    </PageContainer>
  )
}
