import i18n from '../../i18n'

export function relativeTime(iso: string): string {
  const t = i18n.t.bind(i18n)
  const diff = (Date.now() - new Date(iso).getTime()) / 1000
  if (diff < 60) return t('time.justNow')
  if (diff < 3600) return t('time.minutesAgo', { count: Math.floor(diff / 60) })
  if (diff < 86400) return t('time.hoursAgo', { count: Math.floor(diff / 3600) })
  if (diff < 604800) return t('time.daysAgo', { count: Math.floor(diff / 86400) })
  return new Date(iso).toLocaleDateString()
}

export function stripMarkdown(text: string): string {
  return text
    .replace(/^#+ .*$/gm, '')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/\*([^*]+)\*/g, '$1')
    .replace(/\[\[([^\]]+)\]\]/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/```[\s\S]*?```/g, '')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/^[-*+] /gm, '')
    .replace(/^> /gm, '')
    .replace(/\|/g, ' ')
    .replace(/\n+/g, ' ')
    .trim()
}
