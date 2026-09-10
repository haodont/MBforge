import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import zhCN from './locales/zh-CN.json'
import en from './locales/en.json'

export const resources = {
  zh: { translation: zhCN },
  en: { translation: en },
} as const

export type Language = keyof typeof resources

const STORAGE_KEY = 'mbforge_language'

function detectLanguage(): string {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved === 'zh' || saved === 'en') return saved
  } catch {
    // localStorage not available
  }
  try {
    const browserLang = navigator.language.slice(0, 2)
    if (browserLang === 'en') return 'en'
  } catch {
    // navigator not available
  }
  return 'zh'
}

void i18n.use(initReactI18next).init({
  resources,
  lng: detectLanguage(),
  fallbackLng: 'zh',
  interpolation: {
    escapeValue: false,
  },
})

i18n.on('languageChanged', (lng) => {
  try {
    localStorage.setItem(STORAGE_KEY, lng)
  } catch {
    // localStorage not available
  }
})

export default i18n
