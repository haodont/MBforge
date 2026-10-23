/**
 * Covers the `App` shell bootstrap (`@/App`): the library-status gate between
 * the Welcome screen and the AppShell, and that switching resources keeps the
 * research conversation mounted with its draft intact.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import { createQueryClient } from '@/api/query/client'
import { AppProvider } from '@/context/AppContext'
import { ToastProvider } from '@/components/ui'
import { getLibraryStatus } from '@/api/http/library'
import App from '@/App'

// Mock library status endpoint — default to "not configured".
vi.mock('@/api/http/library', () => ({
  getLibraryStatus: vi.fn().mockResolvedValue({ configured: false, root: '', doc_count: 0 }),
  listDocuments: vi.fn().mockResolvedValue({ documents: [] }),
  importDocument: vi.fn(),
  deleteDocuments: vi.fn(),
}))

// Mock i18n — just render children without translation context.
vi.mock('react-i18next', () => ({
  I18nextProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en' },
  }),
  initReactI18next: { type: '3rdParty' },
}))

// App tests cover shell/bootstrap routing; the real Ketcher editor requires
// a browser canvas context, which jsdom does not provide.
vi.mock('@/components/molecule/MoleculeEditorDialog', () => ({
  default: () => null,
}))

function renderApp() {
  const qc = createQueryClient()
  return render(
    <MemoryRouter>
      <QueryClientProvider client={qc}>
        <AppProvider>
          <ToastProvider>
            <App />
          </ToastProvider>
        </AppProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

describe('App', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('gates the shell on the backend library status', async () => {
    // Unconfigured backend: LibraryBootstrap renders the Welcome screen.
    const welcome = renderApp()
    expect(await screen.findByText('library.configureLibrary')).toBeInTheDocument()
    welcome.unmount()

    // The backend is the single source of truth for the library root.
    vi.mocked(getLibraryStatus).mockResolvedValueOnce({
      configured: true,
      root: '/tmp/test-lib',
      doc_count: 0,
    })

    renderApp()
    expect(await screen.findByRole('button', { name: 'nav.workspace' })).toBeInTheDocument()
    // Resource navigation must not unmount the research conversation/draft.
    const input = await screen.findByRole('textbox', { name: 'research.placeholder' })
    fireEvent.change(input, { target: { value: 'Investigate MRGPRX2' } })
    fireEvent.click(screen.getByRole('button', { name: 'nav.workspace' }))
    await screen.findByRole('button', { name: 'research.returnChat' })
    expect(input).toBeInTheDocument()
    expect(input).toHaveValue('Investigate MRGPRX2')
  })
})
