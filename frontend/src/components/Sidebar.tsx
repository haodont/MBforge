import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { FlaskIcon, SettingsIcon, GlobeIcon, FileTextIcon, QueueIcon, CheckIcon, ChatIcon, SparklesIcon } from './icons'
import { Button } from '@/components/ui'
import { useAppContext } from '@/context/AppContext'

const resources = [
  { id: 'workspace', path: '/workspace', icon: FileTextIcon },
  { id: 'molecules', path: '/molecules', icon: FlaskIcon },
  { id: 'queue', path: '/queue', icon: QueueIcon },
  { id: 'review', path: '/review', icon: CheckIcon },
  { id: 'knowledge', path: '/notes', icon: GlobeIcon },
]

export default function Sidebar({ current }: { current: string }) {
  const navigate = useNavigate()
  const { t } = useTranslation()
  const { setActiveTabId, libraryRoot } = useAppContext()
  const go = (path: string) => { setActiveTabId(null); void navigate(path) }
  const libraryName = libraryRoot.split(/[\\/]/).filter(Boolean).pop() || t('research.library')
  return (
    <aside className="app-sidebar">
      <Button variant="ghost" className="app-sidebar__brand" onClick={() => go('/agent')} ariaLabel={t('research.workspace')} icon={<SparklesIcon size={24} />}>
        <span><strong>MBForge</strong><small>{t('research.brand')}</small></span>
      </Button>
      <nav className="app-sidebar__nav" aria-label={t('research.workspace')}>
        <Button variant="ghost" className={'app-sidebar__nav-button' + (current === 'agent' ? ' is-active' : '')}
          ariaLabel={t('nav.agent')} ariaPressed={current === 'agent'} onClick={() => go('/agent')} icon={<ChatIcon size={18} />}><span>{t('nav.agent')}</span></Button>
      </nav>
      <span className="app-sidebar__section-label">{t('research.resources')}</span>
      <nav className="app-sidebar__nav" aria-label={t('research.resources')}>
        {resources.map(({ id, path, icon: Icon }) => <Button key={id} variant="ghost"
          className={'app-sidebar__nav-button' + (current === id ? ' is-active' : '')}
          ariaLabel={t('nav.' + id)} ariaPressed={current === id} title={t('nav.' + id)}
          onClick={() => go(path)} icon={<Icon size={18} />}><span>{t('nav.' + id)}</span></Button>)}
      </nav>
      <div className="app-sidebar__spacer" />
      <div className="app-sidebar__library"><span className="research-model-dot is-configured" /><span title={libraryRoot}>{libraryName}</span></div>
      <nav className="app-sidebar__nav" aria-label={t('research.support')}>
        <Button variant="ghost" className={'app-sidebar__nav-button' + (current === 'docs' ? ' is-active' : '')} ariaLabel={t('nav.docs')} ariaPressed={current === 'docs'} onClick={() => go('/docs')} icon={<FileTextIcon size={18} />}><span>{t('nav.docs')}</span></Button>
        <Button variant="ghost" className={'app-sidebar__nav-button' + (current === 'settings' ? ' is-active' : '')} ariaLabel={t('nav.settings')} ariaPressed={current === 'settings'} onClick={() => go('/settings')} icon={<SettingsIcon size={18} />}><span>{t('nav.settings')}</span></Button>
      </nav>
    </aside>
  )
}
