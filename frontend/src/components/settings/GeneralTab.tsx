/**
 * General tab — UI preferences (theme and language) and AI & Recognition
 * (LLM / VLM / OCR config) on the same page.
 *
 * History: AI & Recognition used to live in its own tab; the
 * ai_recognition entry has been merged here so the most-frequently-touched
 * options are reachable in one place. See PdfProcessingTab for the rest.
 */

import GeneralSection from '@/components/settings/GeneralSection'
import AIModelsSection from '@/components/settings/AIModelsSection'
import type { SettingsState } from '@/components/settings/types'

interface Props {
  settings: SettingsState
  setSettings: React.Dispatch<React.SetStateAction<SettingsState>>
}

export default function GeneralTab({ settings, setSettings }: Props) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-5)' }}>
      <GeneralSection settings={settings} setSettings={setSettings} />
      <AIModelsSection settings={settings} setSettings={setSettings} />
    </div>
  )
}
