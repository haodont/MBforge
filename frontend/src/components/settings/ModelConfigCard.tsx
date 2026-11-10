import { useEffect, useRef, useState } from 'react'
import LlmConfigSection from './model/LlmConfigSection'
import VlmConfigSection from './model/VlmConfigSection'
import LayoutConfigSection from './model/LayoutConfigSection'
import type { SettingsState } from './types'

type ModelType = 'llm' | 'vlm' | 'ocr'

interface Props {
  modelType: ModelType
  title: string
  description?: string
  settings: SettingsState
  setSettings: React.Dispatch<React.SetStateAction<SettingsState>>
}

export default function ModelConfigCard({
  modelType,
  title,
  description,
  settings,
  setSettings,
}: Props) {
  const [dirtyFields, setDirtyFields] = useState<Record<string, boolean>>({})
  const dirtyTimersRef = useRef<Record<string, number | undefined>>({})

  const markDirty = (field: string) => {
    setDirtyFields(d => ({ ...d, [field]: true }))
    clearTimeout(dirtyTimersRef.current[field])
    dirtyTimersRef.current[field] = setTimeout(() => {
      setDirtyFields(d => ({ ...d, [field]: false }))
    }, 1000)
  }

  useEffect(() => {
    const dirtyTimers = dirtyTimersRef.current
    return () => {
      Object.values(dirtyTimers).forEach(clearTimeout)
    }
  }, [])

  const sectionProps = {
    settings,
    setSettings,
    markDirty,
    dirtyFields,
  }

  return (
    <div className="ui-card" style={{ padding: 'var(--space-4)' }}>
      <div className="settings-card-header">
        <div>
          <h3 className="settings-card-title">{title}</h3>
          {description && <p className="settings-card-desc">{description}</p>}
        </div>
      </div>

      {modelType === 'llm' && <LlmConfigSection {...sectionProps} />}
      {modelType === 'vlm' && <VlmConfigSection {...sectionProps} />}
      {modelType === 'ocr' && <LayoutConfigSection {...sectionProps} />}
    </div>
  )
}
