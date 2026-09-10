import { Suspense, lazy, useMemo, useRef, useEffect, useState } from 'react'
import { Routes, Route, useLocation, useNavigate, Navigate } from 'react-router-dom'
import { AnimatePresence } from 'framer-motion'
import { I18nextProvider } from 'react-i18next'
import i18n from './i18n'
import AnimatedPage from './components/animations/AnimatedPage'
import { ErrorState, ToastProvider } from './components/ui'
import { LibraryBootstrap } from './components/app/LibraryBootstrap'
import { AppShell } from './components/app/AppShell'
import { AppProvider, useAppContext } from './context/AppContext'
import PdfViewer from './components/project/PdfViewer'
import DocumentViewer from './components/project/DocumentViewer'
import MarkdownViewer from './components/MarkdownViewer'
import { registerGlobalErrorHandlers } from './api/http/_utils'
import { useSidecarEvents } from './hooks/useSidecarEvents'
import { useIngestNotifications } from './hooks/useIngestNotifications'
import { getLibraryStatus } from './api/http/library'
import { clearViewerSnapshot } from './components/project/pdf/usePdfViewer'
import type { Tab } from './context/AppContext'
import Workspace from './components/workspace/Workspace'
import Docs from './components/Docs'

const MoleculeLibrary = lazy(() => import('./components/MoleculeLibrary'))
const Knowledge = lazy(() => import('./components/Knowledge'))
const ProcessingQueue = lazy(() => import('./components/project/ProcessingQueue'))
const SettingsPage = lazy(() => import('./components/settings/SettingsPage'))
const ReviewCenter = lazy(() => import('./components/review/ReviewCenter'))

/** Lightweight fallback shown while a route chunk is being fetched. */
function RouteFallback() {
  return (
    <div className="route-fallback">
      Loading...
    </div>
  )
}

export default function App() {
  return (
    <I18nextProvider i18n={i18n}>
      <AppProvider>
        <ToastProvider>
          <AppShellOrBootstrap />
        </ToastProvider>
      </AppProvider>
    </I18nextProvider>
  )
}

/**
 * Thin orchestrator — holds lifecycle hooks and chooses between the
 * bootstrap (no library) or the full app shell (library configured).
 */
function AppShellOrBootstrap() {
  const {
    libraryRoot,
    setLibraryRoot,
    openTabs,
    activeTabId,
    closeTab,
  } = useAppContext()
  const location = useLocation()
  const navigate = useNavigate()
  // Memoize so the string reference is stable when ``location.pathname``
  // is unchanged across renders; downstream children (notably
  // ``AppShell``) compare it to decide whether to refresh route data.
  const currentPage = useMemo(
    () => pageFromPath(location.pathname),
    [location.pathname],
  )
  const [libraryStatusChecked, setLibraryStatusChecked] = useState(false)
  const [libraryStatusError, setLibraryStatusError] = useState<Error | null>(null)
  const [libraryStatusRetry, setLibraryStatusRetry] = useState(0)

  useSidecarEvents()
  useIngestNotifications(libraryRoot)

  // Register global error handlers once on mount.
  useEffect(() => {
    const cleanup = registerGlobalErrorHandlers()
    return cleanup
  }, [])

  // Listen for cross-component navigation requests.
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<string>).detail
      if (detail === 'settings') void navigate('/settings')
    }
    window.addEventListener('mbforge:navigate', handler)
    return () => window.removeEventListener('mbforge:navigate', handler)
  }, [navigate])

  // Restore library config from backend on mount. Each retry bumps
  // ``libraryStatusRetry`` which re-runs this effect, so we tag every
  // request with a monotonically increasing token; stale responses from
  // a previous run are discarded so a slow early request cannot clobber
  // the state of a faster later one.
  const statusRequestTokenRef = useRef(0)
  useEffect(() => {
    const token = ++statusRequestTokenRef.current
    setLibraryStatusChecked(false)
    setLibraryStatusError(null)
    void (async () => {
      try {
        const status = await getLibraryStatus()
        if (token !== statusRequestTokenRef.current) return
        if (status.configured && status.root) {
          setLibraryRoot(status.root)
        }
      } catch (error) {
        if (token !== statusRequestTokenRef.current) return
        setLibraryStatusError(error instanceof Error ? error : new Error(String(error)))
        // Backend not reachable yet — keep current state
      } finally {
        if (token === statusRequestTokenRef.current) {
          setLibraryStatusChecked(true)
        }
      }
    })()
  }, [libraryStatusRetry, setLibraryRoot])

  // Keep localStorage in sync with libraryRoot.
  const hasMountedRef = useRef(false)
  useEffect(() => {
    if (!hasMountedRef.current) {
      hasMountedRef.current = true
      return
    }
    if (libraryRoot) {
      localStorage.setItem('mbforge_library_root', libraryRoot)
    } else {
      localStorage.removeItem('mbforge_library_root')
    }
  }, [libraryRoot])

  if (!libraryRoot) {
    if (!libraryStatusChecked) return <RouteFallback />
    if (libraryStatusError) {
      return (
        <div className="app-shell--no-library">
          <ErrorState
            error={libraryStatusError}
            onRetry={() => setLibraryStatusRetry((value) => value + 1)}
          />
        </div>
      )
    }
    if (location.pathname.startsWith('/notes')) {
      return (
        <div className="app-shell--no-library">
          <Knowledge />
        </div>
      )
    }
    if (location.pathname.startsWith('/docs')) {
      return <div className="app-shell--no-library"><Docs /></div>
    }
    return <LibraryBootstrap />
  }

  return (
    <AppShell currentPage={currentPage}>
      {activeTabId === null ? (
        <AppRoutes />
      ) : (
        <TabContent
          activeTabId={activeTabId}
          openTabs={openTabs}
          closeTab={closeTab}
        />
      )}
    </AppShell>
  )
}

function pageFromPath(pathname: string): string {
  const page = pathname.split('/').filter(Boolean)[0]
  if (page === 'analysis') return 'molecules'
  if (page === 'notes') return 'knowledge'
  return page || 'workspace'
}

/** Switch on active tab type: pdf / markdown / document viewer. */
function TabContent({
  activeTabId,
  openTabs,
  closeTab,
}: {
  activeTabId: string
  openTabs: Tab[]
  closeTab: (id: string) => void
}) {
  const activeTab = openTabs.find(t => t.id === activeTabId) ?? null
  if (!activeTab) return null

  switch (activeTab.type) {
    case 'pdf':
      return (
        <PdfViewer
          key={activeTab.id}
          doc={activeTab.doc}
          libraryRoot={activeTab.libraryRoot}
          initialPage={activeTab.initialPage}
          initialBbox={activeTab.initialBbox}
          onClose={() => {
            clearViewerSnapshot(`${activeTab.id}:${activeTab.doc.doc_id}`)
            closeTab(activeTab.id)
          }}
          viewerKey={`${activeTab.id}:${activeTab.doc.doc_id}`}
        />
      )
    case 'markdown':
      return (
        <MarkdownViewer
          libraryRoot={activeTab.libraryRoot}
          docId={activeTab.doc.doc_id}
          onClose={() => closeTab(activeTab.id)}
        />
      )
    case 'document':
      return (
        <DocumentViewer
          key={activeTab.id}
          doc={activeTab.doc}
          libraryRoot={activeTab.libraryRoot}
          initialPage={activeTab.initialPage}
          initialBbox={activeTab.initialBbox}
          onClose={() => {
            clearViewerSnapshot(`${activeTab.id}:${activeTab.doc.doc_id}`)
            closeTab(activeTab.id)
          }}
          viewerKey={`${activeTab.id}:${activeTab.doc.doc_id}`}
        />
      )
    default:
      return null
  }
}

function AppRoutes() {
  const location = useLocation()
  // Keep the Docs route mounted while switching slugs so the article does not
  // replay the page-level enter/exit animation on every document selection.
  const routeKey = location.pathname.startsWith('/docs/') ? '/docs' : location.pathname
  return (
    <AnimatePresence initial={false}>
      <Routes location={location} key={routeKey}>
        <Route path="/" element={<Navigate to="/workspace" replace />} />
        <Route
          path="/workspace"
          element={
            <Suspense fallback={<RouteFallback />}>
              <AnimatedPage><Workspace /></AnimatedPage>
            </Suspense>
          }
        />
        <Route
          path="/molecules"
          element={
            <Suspense fallback={<RouteFallback />}>
              <AnimatedPage><MoleculeLibrary /></AnimatedPage>
            </Suspense>
          }
        />
        <Route path="/analysis" element={<Navigate to="/molecules" replace />} />
        <Route
          path="/settings"
          element={
            <Suspense fallback={<RouteFallback />}>
              <AnimatedPage><SettingsPage /></AnimatedPage>
            </Suspense>
          }
        />
        <Route
          path="/queue"
          element={
            <Suspense fallback={<RouteFallback />}>
              <AnimatedPage><ProcessingQueue /></AnimatedPage>
            </Suspense>
          }
        />
        <Route
          path="/notes"
          element={
            <Suspense fallback={<RouteFallback />}>
              <AnimatedPage><Knowledge /></AnimatedPage>
            </Suspense>
          }
        />
        <Route
          path="/docs"
          element={
            <Suspense fallback={<RouteFallback />}>
              <AnimatedPage><Docs /></AnimatedPage>
            </Suspense>
          }
        />
        <Route
          path="/docs/:slug"
          element={
            <Suspense fallback={<RouteFallback />}>
              <AnimatedPage><Docs /></AnimatedPage>
            </Suspense>
          }
        />
        <Route
          path="/review"
          element={
            <Suspense fallback={<RouteFallback />}>
              <AnimatedPage><ReviewCenter /></AnimatedPage>
            </Suspense>
          }
        />
      </Routes>
    </AnimatePresence>
  )
}
