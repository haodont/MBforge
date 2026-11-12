/**
 * PDF 处理 tab — wraps PdfParseSection which holds MoldDet detection
 * and ingest queue config. Carved out from the old "General" tab so
 * users can find PDF workflow settings in one place.
 */

import PdfParseSection from './PdfParseSection'
import type { SettingsState } from './types'

interface Props {
  settings: SettingsState
  setSettings: React.Dispatch<React.SetStateAction<SettingsState>>
}

export default function PdfProcessingTab({ settings, setSettings }: Props) {
  return <PdfParseSection settings={settings} setSettings={setSettings} />
}