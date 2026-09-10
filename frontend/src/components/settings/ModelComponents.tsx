import { useId } from 'react'
import { useTranslation } from 'react-i18next'
import Input from '@/components/ui/Input'

// ============ ModelSelector ============
// Free-text input + <datalist> suggestions: users can type any model name;
// the browser shows provider-recommended models in the dropdown for reuse
// while still allowing custom entries.
interface ModelSelectorProps {
  provider: string
  modelValue: string
  models: Record<string, { value: string; label: string }[] | undefined>
  onChange: (v: string) => void
  placeholder?: string
}

export function ModelSelector({ provider, modelValue, models, onChange, placeholder }: ModelSelectorProps) {
  const { t } = useTranslation()
  const listId = useId()
  const options = models[provider] ?? []

  return (
    <>
      <Input
        value={modelValue}
        onChange={e => onChange(e.target.value)}
        list={listId}
        placeholder={placeholder ?? t('models.enterModelName')}
        style={{ maxWidth: '100%' }}
      />
      <datalist id={listId}>
        {options.map(o => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </datalist>
    </>
  )
}