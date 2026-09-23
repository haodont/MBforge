/** Primary app shell — full grid layout with sidebar and content area.
 *
 *  Used when a library root is configured.
 */

import type { ReactNode } from 'react'
import Sidebar from '../Sidebar'
import ErrorBoundary from '../ErrorBoundary'
import { ToastContainer } from '../ui'
import '../../styles/AppShell.css'

interface AppShellProps {
  currentPage: string
  /** The active content to render (routes or tab viewers). */
  children: ReactNode
}

export function AppShell({
  currentPage,
  children,
}: AppShellProps) {
  return (
    <div className="app-shell">
      <Sidebar current={currentPage} />
      <main className="app-shell__content">
        <ErrorBoundary>{children}</ErrorBoundary>
      </main>
      <ToastContainer position="bottom-right" />
    </div>
  )
}
