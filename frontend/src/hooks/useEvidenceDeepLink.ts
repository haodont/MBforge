import { useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAppContext } from '@/context/AppContext'
import { documentEntry } from '@/utils/documentEntry'
import { parseEvidenceDeepLink } from '@/utils/evidenceDeepLink'

/**
 * Open a document tab at a cited evidence location when the agent CLI hands off
 * a `/open?doc=&page=&bbox=&evidence=` deep link. Mounted once in the app shell
 * so it fires whether or not a tab is already active.
 */
export function useEvidenceDeepLink(): void {
  const { libraryRoot, openTab } = useAppContext()
  const location = useLocation()
  const navigate = useNavigate()

  useEffect(() => {
    if (location.pathname !== '/open') return
    const target = parseEvidenceDeepLink(location.search)
    if (!target || !libraryRoot) return
    openTab({
      type: 'document',
      title: target.docId,
      doc: documentEntry(target.docId),
      libraryRoot,
      initialPage: target.page,
      initialBbox: target.bbox,
      initialEvidenceId: target.evidenceId,
    })
    void navigate('/workspace', { replace: true })
  }, [location.pathname, location.search, libraryRoot, openTab, navigate])
}