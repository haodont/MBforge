import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { useTranslation } from 'react-i18next'
import {
  FlaskIcon,
  LayoutIcon,
  SettingsIcon,
  GlobeIcon,
  FileTextIcon,
  QueueIcon,
  CheckIcon,
} from './icons'
import Tooltip from '@/components/ui/Tooltip'
import { useAppContext } from '@/context/AppContext'

interface Props {
  current: string
}

interface NavItem {
  id: string
  path: string
  icon: React.FC<{ size?: number }>
  labelKey: string
  preload?: () => Promise<unknown>
}

const PRIMARY_ITEMS: NavItem[] = [
  { id: 'molecules', path: '/molecules', icon: FlaskIcon, labelKey: 'nav.molecules' },
]

const SECONDARY_ITEMS: NavItem[] = [
  {
    id: 'queue',
    path: '/queue',
    icon: QueueIcon,
    labelKey: 'nav.queue',
    // Prefetch the lazy route chunk on hover so the first open is instant.
    preload: () => import('@/components/project/ProcessingQueue'),
  },
  { id: 'knowledge', path: '/notes', icon: GlobeIcon, labelKey: 'nav.knowledge' },
  { id: 'review', path: '/review', icon: CheckIcon, labelKey: 'nav.review' },
]

const FOOTER_ITEMS: NavItem[] = [
  { id: 'docs', path: '/docs', icon: FileTextIcon, labelKey: 'nav.docs' },
]

interface NavButtonProps {
  active: boolean
  onClick: () => void
  label: string
  icon: React.FC<{ size?: number }>
  onHover?: () => void
}

function NavButton({ active, onClick, label, icon: Icon, onHover }: NavButtonProps) {
  return (
    <Tooltip text={label}>
      <motion.button
        className={`app-sidebar__nav-button${active ? ' is-active' : ''}`}
        onClick={onClick}
        onMouseEnter={onHover}
        whileTap={{ scale: 0.96 }}
        aria-current={active ? 'page' : undefined}
      >
        <Icon size={20} />
      </motion.button>
    </Tooltip>
  )
}

export default function Sidebar({ current }: Props) {
  const navigate = useNavigate()
  const { t } = useTranslation()
  const {
    setActiveTabId,
  } = useAppContext()

  const handleClick = (item: NavItem) => {
    setActiveTabId(null)
    void navigate(item.path)
  }

  const libraryLabel = t('nav.workspace')
  const openLibrary = () => {
    setActiveTabId(null)
    void navigate('/workspace')
  }

  return (
    <aside
      className="app-sidebar"
    >
      <Tooltip text={libraryLabel}>
        <motion.button
          type="button"
          onClick={openLibrary}
          aria-label={libraryLabel}
          aria-current={current === 'workspace' ? 'page' : undefined}
          whileTap={{ scale: 0.96 }}
          className="app-sidebar__brand"
        >
          <LayoutIcon size={18} />
        </motion.button>
      </Tooltip>

      <nav className="app-sidebar__nav">
        {PRIMARY_ITEMS.map(item => (
          <NavButton
            key={item.id}
            active={current === item.id}
            onClick={() => handleClick(item)}
            label={t(item.labelKey)}
            icon={item.icon}
          />
        ))}
      </nav>

      <div className="app-sidebar__divider" />

      <nav className="app-sidebar__nav">
        {SECONDARY_ITEMS.map(item => (
          <NavButton
            key={item.id}
            active={current === item.id}
            onClick={() => handleClick(item)}
            label={t(item.labelKey)}
            icon={item.icon}
            onHover={item.preload ? () => { void item.preload?.() } : undefined}
          />
        ))}
      </nav>

      <div className="app-sidebar__spacer" />

      <nav className="app-sidebar__nav app-sidebar__nav--footer">
        {FOOTER_ITEMS.map(item => (
          <NavButton
            key={item.id}
            active={current === item.id}
            onClick={() => handleClick(item)}
            label={t(item.labelKey)}
            icon={item.icon}
          />
        ))}
      </nav>

      <div className="app-sidebar__settings">
        <NavButton
          active={current === 'settings'}
          onClick={() => {
            setActiveTabId(null)
            void navigate('/settings')
          }}
          label={t('nav.settings')}
          icon={SettingsIcon}
        />
      </div>
    </aside>
  )
}
