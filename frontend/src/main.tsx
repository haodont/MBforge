import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { onCLS, onINP, onLCP } from 'web-vitals'
import App from './App'
import { Providers } from './app/Providers'
import './styles/base.css'
import './styles/theme.css'
import './styles/global.css'
import './styles/ui.css'
import './styles/processing-queue.css'
import './styles/pdf-pipeline-flow.css'
import './styles/workspace.css'
import './styles/settings.css'
import './styles/settings-page.css'
import './styles/settings-ocr.css'
import './styles/pdf-toolbar.css'
import './styles/pdf-canvas.css'
import './styles/pdf-continuous.css'
import './styles/molecule-detail.css'
import './styles/notes.css'
import './styles/library.css'
import './styles/molecule-display.css'
import { initTheme } from './hooks/useTheme'

// Initialize theme before React renders to prevent flash
initTheme()

// Web Vitals monitoring — dev: console.log, prod: could be sent to Rust logger
onCLS((metric) => {
  if (import.meta.env.DEV) console.log('[vitals] CLS:', metric.value)
})
onINP((metric) => {
  if (import.meta.env.DEV) console.log('[vitals] INP:', metric.value)
})
onLCP((metric) => {
  if (import.meta.env.DEV) console.log('[vitals] LCP:', metric.value)
})

createRoot(document.getElementById('root') ?? document.body).render(
  <StrictMode>
    <BrowserRouter>
      <Providers>
        <App />
      </Providers>
    </BrowserRouter>
  </StrictMode>,
)
