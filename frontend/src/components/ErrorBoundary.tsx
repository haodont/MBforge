import { Component, type ReactNode } from 'react'
import i18n from '@/i18n'
import { AlertIcon, CopyIcon, CheckIcon } from './icons'
import { reportClientError } from '@/hooks/useErrorReport'
import { logger } from '@/utils/logger'

interface Props {
  children: ReactNode
  /** 捕获错误时的回调，可用于上报 */
  onError?: (error: Error, errorInfo: React.ErrorInfo) => void
}

interface State {
  hasError: boolean
  error?: Error
  copied: boolean
  expanded: boolean
  retryKey: number
}

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false, copied: false, expanded: false, retryKey: 0 }
  }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    logger.error('ErrorBoundary caught:', error, errorInfo)
    // Surface the error to the backend diagnostics ring buffer alongside
    // any server-side errors, so operators see the full chain from one place.
    reportClientError(error, { componentStack: errorInfo.componentStack })
    this.props.onError?.(error, errorInfo)
  }

  handleReset = () => {
    this.setState({ hasError: false, error: undefined, copied: false, expanded: false, retryKey: this.state.retryKey + 1 })
  }

  handleRefresh = () => {
    window.location.reload()
  }

  handleCopy = async () => {
    const { error } = this.state
    if (!error) return
    try {
      await navigator.clipboard.writeText(`[${error.name}] ${error.message}\n${error.stack ?? ''}`)
      this.setState({ copied: true })
      setTimeout(() => this.setState({ copied: false }), 2000)
    } catch {
      // clipboard not available
    }
  }

  toggleDetails = () => {
    this.setState(prev => ({ expanded: !prev.expanded }))
  }

  render() {
    if (this.state.hasError) {
      const { error, copied, expanded } = this.state
      const t = i18n.t.bind(i18n)

      return (
        <div
          style={{
            height: '100%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '24px',
            background: 'var(--bg-base)',
          }}
        >
          <div
            style={{
              maxWidth: '480px',
              width: '100%',
              textAlign: 'center',
              padding: '40px',
              background: 'var(--bg-surface)',
              border: '1px solid var(--border)',
              borderRadius: '16px',
            }}
          >
            <div
              style={{
                width: '56px',
                height: '56px',
                borderRadius: '14px',
                background: 'var(--danger-muted)',
                color: 'var(--danger)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                margin: '0 auto 20px',
              }}
            >
              <AlertIcon size={28} />
            </div>
            <h2 style={{ fontSize: '18px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '8px' }}>
              {t('error.title')}
            </h2>
            <p style={{ fontSize: '14px', color: 'var(--text-secondary)', marginBottom: '20px', lineHeight: 1.5 }}>
              {t('error.description')}
            </p>

            {error && (
              <>
                <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '12px' }}>
                  <button
                    onClick={this.toggleDetails}
                    style={{
                      background: 'none',
                      border: 'none',
                      color: 'var(--accent)',
                      cursor: 'pointer',
                      fontSize: '12px',
                      padding: '4px 8px',
                    }}
                  >
                    {expanded ? t('error.hideDetails') : t('error.showDetails')}
                  </button>
                </div>
                {expanded && (
                  <pre
                    style={{
                      fontSize: '12px',
                      color: 'var(--text-muted)',
                      background: 'var(--bg-base)',
                      padding: '12px',
                      borderRadius: '8px',
                      textAlign: 'left',
                      overflow: 'auto',
                      maxHeight: '160px',
                      marginBottom: '16px',
                      fontFamily: "'Consolas', 'Monaco', monospace",
                    }}
                  >
                    {error.name}: {error.message}
                    {'\n'}
                    {error.stack ?? ''}
                  </pre>
                )}
              </>
            )}

            <div style={{ display: 'flex', gap: '8px', justifyContent: 'center', flexWrap: 'wrap' }}>
              <button
                onClick={this.handleRefresh}
                style={{
                  padding: '10px 24px',
                  background: 'var(--accent)',
                  color: 'var(--text-on-accent)',
                  border: 'none',
                  borderRadius: '10px',
                  fontSize: '14px',
                  fontWeight: 500,
                  cursor: 'pointer',
                  transition: 'background-color 0.15s, color 0.15s, border-color 0.15s',
                }}
                onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--accent-hover)' }}
                onMouseLeave={(e) => { e.currentTarget.style.background = 'var(--accent)' }}
              >
                {t('error.refresh')}
              </button>
              <button
                onClick={this.handleReset}
                style={{
                  padding: '10px 24px',
                  background: 'var(--bg-surface)',
                  color: 'var(--text-primary)',
                  border: '1px solid var(--border)',
                  borderRadius: '10px',
                  fontSize: '14px',
                  fontWeight: 500,
                  cursor: 'pointer',
                  transition: 'background-color 0.15s, color 0.15s, border-color 0.15s',
                }}
              >
                {t('error.retry')}
              </button>
              {error && (
                <button
                  onClick={this.handleCopy}
                  style={{
                    padding: '10px 16px',
                    background: 'transparent',
                    color: 'var(--text-secondary)',
                    border: '1px solid var(--border)',
                    borderRadius: '10px',
                    fontSize: '14px',
                    fontWeight: 500,
                    cursor: 'pointer',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '6px',
                    transition: 'background-color 0.15s, color 0.15s, border-color 0.15s',
                  }}
                >
                  {copied ? <CheckIcon size={16} /> : <CopyIcon size={16} />}
                  {copied ? t('error.detailsCopied') : t('error.copyDetails')}
                </button>
              )}
            </div>
          </div>
        </div>
      )
    }

    return (
      <div
        key={this.state.retryKey}
        style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0, overflow: 'hidden' }}
      >
        {this.props.children}
      </div>
    )
  }
}