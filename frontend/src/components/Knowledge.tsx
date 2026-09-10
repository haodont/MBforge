import { useTranslation } from 'react-i18next'
import Notes from './Notes'
import './knowledge.css'

export default function Knowledge() {
  const { t } = useTranslation()

  return (
    <div className="knowledge-workspace">
      <header className="knowledge-switcher">
        <div>
          <span className="knowledge-switcher__eyebrow">{t('knowledge.eyebrow')}</span>
          <h1>{t('knowledge.title')}</h1>
        </div>
        <p className="knowledge-switcher__hint">
          {t('knowledge.hint.notes')}
        </p>
      </header>
      <main className="knowledge-workspace__body">
        <Notes />
      </main>
    </div>
  )
}
