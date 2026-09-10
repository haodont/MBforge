// Reusable API key input: show/hide toggle + copy to clipboard.
// Shared across the LLM / VLM / OCR / embedding sections.

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import Input from '@/components/ui/Input'
import IconButton from '@/components/ui/IconButton'
import { EyeIcon, EyeOffIcon, CopyIcon, CheckIcon } from '../icons'

interface Props {
  value: string
  onChange: (v: string) => void
  placeholder?: string
}

export default function ApiKeyInput({ value, onChange, placeholder = 'sk-...' }: Props) {
  const { t } = useTranslation()
  const [visible, setVisible] = useState(false)
  const [copied, setCopied] = useState(false)

  const copy = async () => {
    if (!value) return
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // Ignore: clipboard permission may be unavailable
    }
  }

  return (
    <div style={{ display: 'flex', gap: 'var(--space-1)', alignItems: 'center', width: '100%' }}>
      <Input
        type={visible ? 'text' : 'password'}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        style={{ flex: 1, fontFamily: 'var(--font-mono, monospace)' }}
      />
      <IconButton
        size={32}
        onClick={copy}
        disabled={!value}
        title={t('common.copy')}
        aria-label={t('common.copy')}
      >
        {copied ? <CheckIcon size={16} /> : <CopyIcon size={16} />}
      </IconButton>
      <IconButton
        size={32}
        onClick={() => setVisible(v => !v)}
        title={visible ? t('settings.apiKeyHide') : t('settings.apiKeyShow')}
        aria-label={visible ? t('settings.apiKeyHide') : t('settings.apiKeyShow')}
      >
        {visible ? <EyeOffIcon size={16} /> : <EyeIcon size={16} />}
      </IconButton>
    </div>
  )
}