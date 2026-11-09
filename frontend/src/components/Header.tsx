import { useTranslation } from 'react-i18next'
import { Breadcrumb } from './ui'

interface HeaderProps {
  currentPage: string
}

export default function Header({ currentPage }: HeaderProps) {
  const { t } = useTranslation()
  const pageTitle: Record<string, string> = {
    workspace: t('nav.workspace'),
    molecules: t('nav.molecules'),
    queue: t('nav.queue'),
    knowledge: t('nav.knowledge'),
    docs: t('nav.docs'),
    settings: t('nav.settings'),
  }

  const title = pageTitle[currentPage] || 'MBForge'

  const pagePath: Record<string, string> = {
    workspace: '/workspace',
    molecules: '/molecules',
    queue: '/queue',
    knowledge: '/notes',
    docs: '/docs',
    settings: '/settings',
  }

  return (
    <header className="app-header">
      <Breadcrumb
        className="app-header__breadcrumb"
        size="lg"
        items={[{ label: title, href: pagePath[currentPage], current: true }]}
      />
      <div className="app-header__spacer" />
    </header>
  )
}
