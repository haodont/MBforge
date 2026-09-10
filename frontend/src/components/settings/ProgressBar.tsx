import { useTranslation } from 'react-i18next'
import type { DownloadState } from './ModelsTab'

interface ProgressBarProps {
  state: DownloadState[string] | undefined
}

export default function ProgressBar({ state }: ProgressBarProps) {
  const { t } = useTranslation()
  if (!state || state.status === 'idle') return null
  const progress = state.progress || 0

  return (
    <div className="settings-progress-bar">
      {state.status === 'connecting' && (
        <span className="settings-progress-status">
          {t('models.downloading')} {state.source && t('models.fromSource', { source: state.source })}
        </span>
      )}
      {state.status === 'downloading' && (
        <>
          <div className="download-progress">
            <div className="download-progress-bar">
              <div className="download-progress-fill" style={{ width: `${progress}%` }} />
            </div>
            <span className="download-progress-text">{progress}%</span>
          </div>
          {state.fileName && (
            <div className="settings-progress-file">
              {state.fileName}
              {state.fileIndex && state.totalFiles && ` (${state.fileIndex}/${state.totalFiles})`}
            </div>
          )}
        </>
      )}
      {state.status === 'completed' && (
        <span className="settings-progress-status settings-progress-status--success">
          {t('models.downloadComplete')} {state.source && t('models.fromSource', { source: state.source })}
        </span>
      )}
      {state.status === 'failed' && (
        <span className="settings-progress-status settings-progress-status--error">
          {state.error || t('models.downloadFailed')}
        </span>
      )}
    </div>
  )
}
